"""Declarative raster grid requirements using the existing input metadata read."""

import math

from .packages import ComputeError

DTYPES = {"uint8", "uint16", "uint32", "int8", "int16", "int32", "float32", "float64"}


def validate_contract(value):
    if not isinstance(value, dict) or set(value) - {
        "bandCount",
        "dtypes",
        "pixelSizeMeters",
        "minSide",
        "northUp",
        "window",
        "cube",
        "streaming",
        "defaultExtent",
        "months",
        "sameYear",
    }:
        raise ComputeError("栅格输入合同包含未知字段")
    if "cube" in value:
        cube = value["cube"]
        if (
            not isinstance(cube, dict)
            or set(cube)
            != {"family", "variableParameter", "timeParameter", "historyParameter"}
            or cube["family"] != "seasfire_observation_v04"
            or any(
                not isinstance(cube[key], str) or not cube[key].isidentifier()
                for key in ("variableParameter", "timeParameter", "historyParameter")
            )
            or "window" not in value
        ):
            raise ComputeError("原生观测合同须声明变量、时间、序列参数和研究区")
    for name in ("streaming", "defaultExtent", "sameYear"):
        if name in value and (type(value[name]) is not bool or "window" not in value):
            raise ComputeError("流式处理和默认全域须绑定有效的研究区窗口")
    if "months" in value and (
        not isinstance(value["months"], list)
        or not value["months"]
        or any(
            type(month) is not int or not 1 <= month <= 12 for month in value["months"]
        )
    ):
        raise ComputeError("模型时相月份声明无效")
    if "window" in value and (
        not isinstance(value["window"], list)
        or len(value["window"]) != 4
        or any(
            not isinstance(key, str) or not key.isidentifier()
            for key in value["window"]
        )
        or len(set(value["window"])) != 4
    ):
        raise ComputeError("研究区窗口须绑定四个不同的数值参数")
    for name, maximum in [("bandCount", 1024), ("minSide", 1000000)]:
        if name in value and (
            type(value[name]) is not int or not 1 <= value[name] <= maximum
        ):
            raise ComputeError("栅格输入合同数量无效")
    if "dtypes" in value and (
        not isinstance(value["dtypes"], list)
        or not value["dtypes"]
        or any(not isinstance(v, str) or v not in DTYPES for v in value["dtypes"])
    ):
        raise ComputeError("栅格输入类型合同无效")
    if "pixelSizeMeters" in value and (
        type(value["pixelSizeMeters"]) not in {int, float}
        or not math.isfinite(value["pixelSizeMeters"])
        or value["pixelSizeMeters"] <= 0
    ):
        raise ComputeError("栅格分辨率合同无效")
    if "northUp" in value and type(value["northUp"]) is not bool:
        raise ComputeError("栅格朝向合同须为布尔值")
    return value


def gaps(spec, info, max_band_pixels=None):
    from .preflight import gap

    contract = spec.get("raster")
    metadata = info.get("rasterMetadata")
    if not contract and max_band_pixels is None:
        return []
    if not isinstance(metadata, dict):
        return [
            gap(
                "RASTER_METADATA",
                spec["key"],
                "replace_data",
                expected="原始栅格网格元信息",
            )
        ]
    rows = []
    bands = metadata["bands"]
    size = metadata["size"]
    transform = metadata["geoTransform"]
    contract = contract or {}

    def add(code, expected, actual):
        rows.append(
            gap(code, spec["key"], "replace_data", expected=expected, actual=actual)
        )

    working_pixels = (
        min(size[0], 256) * min(size[1], 256)
        if contract.get("streaming")
        else size[0] * size[1]
    )
    if max_band_pixels is not None and working_pixels * len(bands) > max_band_pixels:
        add("RASTER_SIZE", max_band_pixels, working_pixels * len(bands))
    if contract.get("bandCount") is not None and len(bands) != contract["bandCount"]:
        add("BAND_COUNT", contract["bandCount"], len(bands))
    if contract.get("dtypes") and any(
        row["type"] not in contract["dtypes"] for row in bands
    ):
        add("RASTER_DTYPE", contract["dtypes"], [row["type"] for row in bands])
    if contract.get("minSide") and min(size) < contract["minSide"]:
        add("RASTER_SIDE", contract["minSide"], size)
    if contract.get("northUp") and (
        transform[2] or transform[4] or transform[1] <= 0 or transform[5] >= 0
    ):
        add("RASTER_ORIENTATION", "north_up", transform)
    if contract.get("pixelSizeMeters") is not None:
        scale = metadata.get("linearUnitMeters")
        if scale is None or any(
            not math.isclose(abs(v) * scale, contract["pixelSizeMeters"], rel_tol=1e-8)
            for v in (transform[1], transform[5])
        ):
            add(
                "RASTER_RESOLUTION",
                contract["pixelSizeMeters"],
                {"transform": transform, "unitMeters": scale},
            )
    return rows
