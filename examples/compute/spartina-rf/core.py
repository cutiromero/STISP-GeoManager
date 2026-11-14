"""Three-season RF interpretation on a bounded original WGS84 grid."""

from contextlib import ExitStack
from pathlib import Path

# CONFIGURATION
BANDS = [
    "B1",
    "B2",
    "B3",
    "B4",
    "B5",
    "B6",
    "B7",
    "B8",
    "B8A",
    "B9",
    "B11",
    "B12",
    "NDVI",
    "NDWI",
    "NBR",
    "EVI",
]
ROLES = ["march", "august", "december"]
BLOCK_SIZE = 256
COLOR = "#65D8A4"


def infer(paths, model, output, progress=lambda *_: None):
    import numpy as np
    import rasterio
    from rasterio.windows import Window
    from pyproj import Geod
    from scipy.ndimage import label

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    classes = np.asarray(model.classes_)
    if model.n_features_in_ != 48 or classes.tolist() != [0, 1]:
        raise ValueError("权重须为48特征、0/1分类的互花米草模型")
    with ExitStack() as stack:
        sources = [stack.enter_context(rasterio.open(paths[role])) for role in ROLES]
        first = sources[0]
        grid = (first.width, first.height, first.transform, first.crs)
        if (
            first.crs.to_epsg() != 4326
            or first.transform.b
            or first.transform.d
            or first.width * first.height > 4194304
        ):
            raise ValueError("输入须为有界北向上WGS84原始窗口")
        for source in sources:
            if (
                source.width,
                source.height,
                source.transform,
                source.crs,
            ) != grid or source.count != 16:
                raise ValueError("三个季节须具有一致原始网格及16波段")
            if (
                any(name is not None for name in source.descriptions)
                and list(source.descriptions) != BANDS
            ):
                raise ValueError("输入波段顺序与交付RF特征不一致")
        profile = {
            **first.profile,
            "driver": "GTiff",
            "count": 1,
            "dtype": "uint8",
            "nodata": 255,
            "tiled": True,
            "blockxsize": 256,
            "blockysize": 256,
            "compress": "deflate",
        }
        classification = stack.enter_context(
            rasterio.open(output / "classification.tif", "w", **profile)
        )
        probability = stack.enter_context(
            rasterio.open(
                output / "probability.tif",
                "w",
                **{**profile, "dtype": "float32", "nodata": -9999},
            )
        )
        classification.write_colormap(
            1, {0: (0, 0, 0, 0), 1: (101, 216, 164, 255), 255: (0, 0, 0, 0)}
        )
        import json

        classification.update_tags(
            stisp_categorical=json.dumps(
                {
                    "schemaVersion": 1,
                    "legend": [
                        {"code": 0, "name": "非目标区", "rgba": [0, 0, 0, 0]},
                        {"code": 1, "name": "互花米草", "rgba": [101, 216, 164, 255]},
                        {"code": 255, "name": "无效区", "rgba": [0, 0, 0, 0]},
                    ],
                    "transparentValues": [0, 255],
                },
                ensure_ascii=False,
            )
        )
        mask = np.zeros((first.height, first.width), dtype=np.uint8)
        target_per_row = np.zeros(first.height, dtype=np.int64)
        valid_per_row = np.zeros(first.height, dtype=np.int64)
        total = ((first.width + 255) // 256) * ((first.height + 255) // 256)
        count = 0
        for row in range(0, first.height, BLOCK_SIZE):
            for col in range(0, first.width, BLOCK_SIZE):
                height, width = (
                    min(BLOCK_SIZE, first.height - row),
                    min(BLOCK_SIZE, first.width - col),
                )
                window = Window(col, row, width, height)
                blocks = [
                    source.read(window=window, masked=True).astype("float32")
                    for source in sources
                ]
                values = np.ma.concatenate(blocks, axis=0)
                features = values.filled(np.nan).reshape(48, -1).T
                valid = np.isfinite(features).all(axis=1)
                result = np.full(height * width, 255, dtype="uint8")
                chance = np.full(height * width, -9999, dtype="float32")
                if valid.any():
                    data = features[valid]
                    prediction = model.predict(data)
                    probabilities = model.predict_proba(data)[
                        :, int(np.flatnonzero(classes == 1)[0])
                    ]
                    if (
                        not np.isfinite(probabilities).all()
                        or (probabilities < 0).any()
                        or (probabilities > 1).any()
                        or not np.isin(prediction, [0, 1]).all()
                    ):
                        raise ValueError("模型输出不是有效分类与概率")
                    result[valid] = prediction
                    chance[valid] = probabilities
                result = result.reshape(height, width)
                target = result == 1
                mask[row : row + height, col : col + width] = target
                target_per_row[row : row + height] += target.sum(axis=1)
                valid_per_row[row : row + height] += (result != 255).sum(axis=1)
                classification.write(result, 1, window=window)
                probability.write(chance.reshape(height, width), 1, window=window)
                count += 1
                progress("模型解译", 30 + int(count / total * 40))
        # A display-only RGB preview of the actual August window; model features stay unchanged.
        preview_values = sources[1].read([4, 3, 2], masked=True)
        rgb = np.zeros((3, first.height, first.width), dtype="uint8")
        for index in range(3):
            valid_values = preview_values[index].compressed()
            valid_values = valid_values[np.isfinite(valid_values)]
            if valid_values.size:
                low, high = np.percentile(
                    valid_values[:: max(1, valid_values.size // 20000)], [2, 98]
                )
                high = max(high, low + 1e-6)
                rgb[index] = (
                    np.clip(
                        (preview_values[index].filled(low) - low) / (high - low), 0, 1
                    )
                    * 255
                ).astype("uint8")
        with rasterio.open(
            output / "original.tif",
            "w",
            **{**profile, "count": 3, "dtype": "uint8", "nodata": None},
        ) as preview:
            preview.write(rgb)
            preview.write_mask(
                (~np.ma.getmaskarray(preview_values).any(axis=0)).astype("uint8") * 255
            )
            preview.colorinterp = (
                rasterio.enums.ColorInterp.red,
                rasterio.enums.ColorInterp.green,
                rasterio.enums.ColorInterp.blue,
            )
            preview.update_tags(stisp_imagery="rgb")
        geod = Geod(ellps="WGS84")
        area_per_row = []
        transform = first.transform
        for row in range(first.height):
            west, north = transform * (0, row)
            east, south = transform * (1, row + 1)
            area_per_row.append(
                abs(
                    geod.polygon_area_perimeter(
                        [west, east, east, west], [north, north, south, south]
                    )[0]
                )
            )
        target_area = float(np.dot(target_per_row, area_per_row))
        valid_area = float(np.dot(valid_per_row, area_per_row))
        _, patch_count = label(mask, structure=np.ones((3, 3), dtype="uint8"))
        statistics = {
            "area_ha": target_area / 10000,
            "patch_count": int(patch_count),
            "valid_area_km2": valid_area / 1000000,
            "coverage_percent": target_area / valid_area * 100 if valid_area else 0,
        }
        return {
            "statistics": statistics,
            "validPixelCount": int(valid_per_row.sum()),
            "targetPixelCount": int(target_per_row.sum()),
            "bounds": list(first.bounds),
            "grid": {
                "width": first.width,
                "height": first.height,
                "transform": list(first.transform)[:6],
                "crs": "EPSG:4326",
            },
            "method": "RF",
            "inputPeriods": ["2025-03", "2025-08", "2025-12"],
            "normalization": "输入16波段原值，三季节顺序拼接",
            "connectivity": 8,
        }
