"""Read bounded native SeasFire arrays using installed GDAL, without zarr/xarray."""

from datetime import date, timedelta
import json
import math
from pathlib import Path
import re

# CONFIGURATION
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_DECODED_RESULT_BYTES = 256 * 1024 * 1024
PRODUCTS = {
    "gwis_ba": {
        "unit": "ha",
        "mode": "8day",
        "mask": "gwis_ba_valid_mask",
        "aggregation": "sum",
    },
    "gfed_ba": {
        "unit": "ha",
        "mode": "8day",
        "mask": "gfed_ba_valid_mask",
        "aggregation": "sum",
    },
    "fcci_ba": {
        "unit": "ha",
        "mode": "monthly",
        "mask": "fcci_ba_valid_mask",
        "aggregation": "mean",
    },
    "cams_frpfire": {
        "unit": "W m-2",
        "mode": "8day",
        "mask": None,
        "aggregation": "mean",
    },
}


class Cube:
    def __init__(self, root):
        from osgeo import gdal
        import numpy as np

        self.root = Path(root).resolve()
        path = self.root / ".zmetadata"
        if not path.is_file() or path.stat().st_size > MAX_METADATA_BYTES:
            raise ValueError("数据立方体元信息缺失或超出范围")
        self.metadata = json.loads(path.read_text())["metadata"]
        for key, schema in self.metadata.items():
            if (
                key.endswith("/.zarray")
                and math.prod(schema["chunks"]) * np.dtype(schema["dtype"]).itemsize
                > 512 * 1024 * 1024
            ):
                raise ValueError("原生数组单块解码超过512MiB预算")
        gdal.UseExceptions()
        self.dataset = gdal.OpenEx(str(self.root), gdal.OF_MULTIDIM_RASTER)
        self.group = self.dataset.GetRootGroup()
        self.latitude = self.read("latitude")
        self.longitude = self.read("longitude")
        rawtime = self.read("time")
        units = self.attrs("time")["units"]
        if not units.startswith("days since "):
            raise ValueError("时间单位与SeasFire原始定义不符")
        epoch = date.fromisoformat(units.removeprefix("days since ").split()[0])
        self.dates = [epoch + timedelta(days=int(value)) for value in rawtime]
        if len(self.dates) != len(set(self.dates)) or self.dates != sorted(self.dates):
            raise ValueError("时间轴不是独立有序观测期")
        if not np.all(np.diff(self.latitude) < 0) or not np.all(
            np.diff(self.longitude) > 0
        ):
            raise ValueError("经纬度方向不符合当前适配要求")
        if not np.allclose(np.diff(self.latitude), -0.25) or not np.allclose(
            np.diff(self.longitude), 0.25
        ):
            raise ValueError("数据不是SeasFire 0.25度格网")

    def attrs(self, name):
        return self.metadata[name + "/.zattrs"]

    def schema(self, name):
        return self.metadata[name + "/.zarray"]

    def read(self, name, start=None, count=None):
        import numpy as np

        if (
            not re.fullmatch("[a-z][a-z0-9_]*", name)
            or name + "/.zarray" not in self.metadata
        ):
            raise ValueError("变量不存在")
        spec = self.schema(name)
        shape = spec["shape"]
        start = start or [0] * len(shape)
        count = count or shape
        if (
            len(start) != len(shape)
            or len(count) != len(shape)
            or any(type(v) is not int or v < 0 for v in start)
            or any(type(v) is not int or v < 1 for v in count)
            or any(
                begin + size > limit for begin, size, limit in zip(start, count, shape)
            )
            or math.prod(count) * np.dtype(spec["dtype"]).itemsize
            > MAX_DECODED_RESULT_BYTES
        ):
            raise ValueError("读取范围或解码结果超过预算")
        array = self.group.OpenMDArray(name)
        raw = array.Read(array_start_idx=start, count=count)
        if raw is None:
            raise ValueError("无法读取原始数组")
        return (
            np.frombuffer(raw, dtype=np.dtype(spec["dtype"]).newbyteorder("="))
            .reshape(count)
            .copy()
        )

    def period(self, index, product):
        day = self.dates[index]
        if PRODUCTS[product]["mode"] == "monthly":
            first = day.replace(day=1)
            nextmonth = (
                date(first.year + 1, 1, 1)
                if first.month == 12
                else date(first.year, first.month + 1, 1)
            )
            return first, nextmonth - timedelta(days=1)
        return day, (self.dates[index + 1] - timedelta(days=1)) if index + 1 < len(
            self.dates
        ) else min(day + timedelta(days=7), date(day.year, 12, 31))

    def window(self, bounds):
        import numpy as np

        west, south, east, north = bounds
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError("研究区边界无效")
        cols = np.flatnonzero((self.longitude >= west) & (self.longitude < east))
        rows = np.flatnonzero((self.latitude <= north) & (self.latitude > south))
        if not len(rows) or not len(cols):
            raise ValueError("研究区内没有格网中心")
        return int(rows[0]), int(cols[0]), len(rows), len(cols)

    def plan(self, product, index, bounds, history=12):
        import numpy as np

        if (
            product not in PRODUCTS
            or type(index) is not int
            or not 0 <= index < len(self.dates)
            or type(history) is not int
            or not 1 <= history <= 12
        ):
            raise ValueError("观测源、时间索引或序列长度无效")
        expected = PRODUCTS[product]
        if self.attrs(product).get("_ARRAY_DIMENSIONS") != [
            "time",
            "latitude",
            "longitude",
        ]:
            raise ValueError("观测数组时空维度不符合要求")
        unit = self.attrs(product).get("units")
        if unit not in (
            {"ha", "hectares (ha)"} if expected["unit"] == "ha" else {"W m-2", "W/m2"}
        ):
            raise ValueError("观测单位与发布规则不符")
        mask = (
            self.read(expected["mask"]).astype(bool)
            if expected["mask"]
            else np.ones(len(self.dates), dtype=bool)
        )
        if not mask[index]:
            raise ValueError("该产品在所选时期无有效观测")
        row, col, height, width = self.window(bounds)
        if expected["mode"] == "monthly":
            periods = []
            for position in range(index, -1, -1):
                key = self.dates[position].strftime("%Y-%m")
                if key not in periods:
                    periods.append(key)
                if len(periods) >= history:
                    break
            periods = periods[::-1]
            groups = [
                [
                    i
                    for i, day in enumerate(self.dates)
                    if day.strftime("%Y-%m") == period
                ]
                for period in periods
            ]
        else:
            groups = [[i] for i in range(max(0, index - history + 1), index + 1)]
        if (
            max(groups[-1]) - min(groups[0]) + 1
        ) * height * width * 4 > MAX_DECODED_RESULT_BYTES:
            raise ValueError("所选研究区与时序的解码结果超出预算")
        return {
            "product": product,
            "index": index,
            "history": history,
            "bounds": list(bounds),
            "window": [row, col, height, width],
            "groups": groups,
            "unit": expected["unit"],
            "periodMode": expected["mode"],
            "periods": [
                [day.isoformat() for day in self.period(group[0], product)]
                for group in groups
            ],
        }

    def observation(self, product, index, bounds, history=12, *, return_frames=False):
        import numpy as np

        plan = self.plan(product, index, bounds, history)
        policy = PRODUCTS[product]
        mask = (
            self.read(policy["mask"]).astype(bool)
            if policy["mask"]
            else np.ones(len(self.dates), dtype=bool)
        )
        row, col, height, width = plan["window"]
        groups = plan["groups"]
        selected = [value for group in groups for value in group]
        first, last = min(selected), max(selected)
        values = self.read(
            product, [first, row, col], [last - first + 1, height, width]
        ).astype("float32")
        values[~mask[first : last + 1]] = np.nan
        series = []
        output_frames = []
        current = None
        for group in groups:
            data = values[np.array(group) - first]
            if policy["mode"] == "monthly":
                with np.errstate(invalid="ignore", divide="ignore"):
                    counts = np.isfinite(data).sum(axis=0)
                    raster = np.divide(
                        np.nansum(data, axis=0, dtype=np.float64),
                        counts,
                        out=np.full((height, width), np.nan, dtype="float32"),
                        where=counts > 0,
                    )
            else:
                raster = data[0]
            finite = np.isfinite(raster)
            positive = finite & (raster > 0)
            begin, end = self.period(group[0], product)
            summary = {
                "observedStart": begin.isoformat(),
                "observedEnd": end.isoformat(),
                "value": float(raster[finite].sum(dtype=np.float64))
                if policy["unit"] == "ha" and finite.any()
                else float(raster[finite].mean(dtype=np.float64))
                if finite.any()
                else None,
                "validCells": int(finite.sum()),
                "activeCells": int(positive.sum()),
                "unit": policy["unit"],
            }
            series.append(summary)
            output_frames.append(raster)
            if index in group:
                current = raster
        transform = [
            float(self.longitude[col] - 0.125),
            0.25,
            0,
            float(self.latitude[row] + 0.125),
            0,
            -0.25,
        ]
        return (np.stack(output_frames) if return_frames else current), {
            "product": product,
            "periodMode": policy["mode"],
            "unit": policy["unit"],
            "series": series,
            "current": series[-1],
            "grid": {
                "width": width,
                "height": height,
                "transform": transform,
                "crs": "EPSG:4326",
            },
            "sourceIndex": index,
            "bounds": bounds,
            "validMask": policy["mask"],
        }
