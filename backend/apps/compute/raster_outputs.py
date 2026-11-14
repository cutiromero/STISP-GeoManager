"""Typed categorical output handoff, validated during the existing raster read."""

import json

from .packages import ComputeError

TAG = "stisp_categorical"


def categorical_metadata(source):
    raw = source.tags().get(TAG)
    if raw is None:
        return None
    if (
        len(raw.encode()) > 32768
        or source.count != 1
        or not source.dtypes[0].startswith(("uint", "int"))
    ):
        raise ComputeError("分类成果声明与实际栅格不一致")
    try:
        value = json.loads(raw)
    except (ValueError, TypeError) as error:
        raise ComputeError("分类成果图例格式无效") from error
    if (
        not isinstance(value, dict)
        or set(value) != {"schemaVersion", "legend", "transparentValues"}
        or value["schemaVersion"] != 1
    ):
        raise ComputeError("分类成果图例协议无效")
    rows = value["legend"]
    transparent = value["transparentValues"]
    if (
        not isinstance(rows, list)
        or not 1 <= len(rows) <= 256
        or not isinstance(transparent, list)
        or any(type(v) is not int for v in transparent)
        or len(set(transparent)) != len(transparent)
    ):
        raise ComputeError("分类图例必须包含有界类别及透明值")
    codes = set()
    try:
        palette = source.colormap(1)
    except ValueError as error:
        raise ComputeError("分类成果缺少实际色表") from error
    for item in rows:
        if (
            not isinstance(item, dict)
            or set(item) != {"code", "name", "rgba"}
            or type(item["code"]) is not int
            or not 0 <= item["code"] <= 255
            or item["code"] in codes
            or not isinstance(item["name"], str)
            or not 1 <= len(item["name"]) <= 120
            or not isinstance(item["rgba"], list)
            or len(item["rgba"]) != 4
            or any(type(v) is not int or not 0 <= v <= 255 for v in item["rgba"])
        ):
            raise ComputeError("分类图例包含无效或重复类别")
        if list(palette.get(item["code"], ())[:3]) != item["rgba"][:3]:
            raise ComputeError("实际栅格色表与成果图例不一致")
        if (item["code"] in transparent) != (item["rgba"][3] == 0):
            raise ComputeError("图例透明度与透明值声明不一致")
        codes.add(item["code"])
    if (
        not set(transparent) <= codes
        or source.nodata is None
        or int(source.nodata) not in transparent
    ):
        raise ComputeError("分类成果无效值未声明为透明")
    return {
        "legend": rows,
        "transparentValues": transparent,
        "rasterKind": "categorical",
    }


def rendering_rules(metadata):
    return {
        "mode": "unique",
        "bands": [1],
        "stretch": {"enabled": False},
        "alphaBand": "mask",
        "nodata": {"enabled": True},
        "uniqueValues": [
            {
                "value": row["code"],
                "label": row["name"],
                "color": "#" + "".join(f"{v:02x}" for v in row["rgba"]),
            }
            for row in metadata["legend"]
        ],
    }
