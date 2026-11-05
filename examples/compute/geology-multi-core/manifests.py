"""Declarative manifest builder for the four first-party trial operators."""

import json
from pathlib import Path


def create():
    def vector(key, label, geometry):
        return {"key": key, "label": label, "kind": "vector", "geometryTypes": geometry}

    def output(key, label, kind, filename):
        return {"key": key, "label": label, "kind": kind, "file": filename}

    polygons, lines, points = (
        ["Polygon", "MultiPolygon"],
        ["LineString", "MultiLineString"],
        ["Point", "MultiPoint"],
    )
    base = [
        vector("lithology", "岩性图", polygons),
        vector("faults", "构造图", lines),
        vector("coverage", "研究区制图范围", polygons),
        {"key": "rules", "label": "显式启用的试用规则及版本", "kind": "table"},
    ]
    rasters = [
        {
            "key": key,
            "label": label + "遥感矿物识别结果",
            "kind": "raster",
            "minBands": 1,
        }
        for key, label in [
            ("hematite", "赤铁矿"),
            ("chlorite", "绿泥石"),
            ("hydromica", "水云母"),
            ("calcite", "方解石"),
            ("dolomite", "白云石"),
        ]
    ]
    parameters = [
        {
            "key": "working_epsg",
            "label": "米制工作投影EPSG",
            "type": "integer",
            "default": 32646,
            "min": 1,
            "max": 999999,
        },
        {
            "key": "segment",
            "label": "本次检查范围",
            "type": "enum",
            "default": "all",
            "choices": ["all", "lithology", "structure", "alteration"],
        },
        {
            "key": "grid_resolution_m",
            "label": "综合分析网格（米）",
            "type": "number",
            "default": 100,
            "min": 10,
            "max": 1000,
        },
        {
            "key": "min_zone_area_m2",
            "label": "远景区最小面积（平方米）",
            "type": "number",
            "default": 200000,
            "min": 0,
            "max": 100000000,
        },
    ]
    maps = [
        output(key, label, "vector", key + ".gpkg")
        for key, label in [
            ("lithology_issues", "岩性疑点"),
            ("fault_issues", "构造疑点"),
            ("alteration_issues", "矿物识别疑点"),
        ]
    ]
    optional_state = {
        **vector("alterations", "已有矿物处理状态（可选）", polygons),
        "required": False,
    }
    variants = {
        "check": (
            "三要素知识检查",
            base + rasters + [optional_state],
            [
                output("issues", "发现的问题与建议", "table", "issues.csv"),
                output(
                    "alterations", "矿物识别与当前状态", "vector", "alterations.gpkg"
                ),
                output("statistics", "按实际规则检查统计", "table", "statistics.csv"),
            ]
            + maps,
        ),
        "apply": (
            "获批操作执行",
            base
            + rasters
            + [
                optional_state,
                {"key": "issues", "label": "本轮完整检查清单", "kind": "table"},
                {"key": "approved_changes", "label": "逐项批准的操作", "kind": "table"},
            ],
            [
                output("lithology", "修正后岩性图", "vector", "lithology.gpkg"),
                output("faults", "修正后构造及处理状态", "vector", "faults.gpkg"),
                output("alterations", "矿物处理状态", "vector", "alterations.gpkg"),
                output("final_faults", "修正后构造图", "vector", "final_faults.gpkg"),
                output(
                    "final_alterations", "有效蚀变", "vector", "final_alterations.gpkg"
                ),
                output("changes", "实际执行的操作", "table", "changes.csv"),
                output("statistics", "岩性前后面积统计", "table", "statistics.csv"),
            ]
            + [
                output(
                    "changes_" + row["key"],
                    "修正记录 " + row["label"],
                    "vector",
                    "changes_" + row["file"],
                )
                for row in maps
            ],
        ),
        "relations": (
            "构造关系重建",
            [
                base[1],
                base[2],
                base[3],
                {
                    **vector("before_faults", "处理前构造图（比较用）", lines),
                    "required": False,
                },
            ],
            [
                output(
                    "before_intersections",
                    "处理前几何与推测交汇点",
                    "vector",
                    "before_intersections.gpkg",
                ),
                output(
                    "intersections", "几何与推测交汇点", "vector", "intersections.gpkg"
                ),
                output("statistics", "交汇关系统计", "table", "statistics.csv"),
            ],
        ),
        "prospect": (
            "优先核查远景区分析",
            base
            + rasters
            + [
                vector("before_lithology", "修改前岩性图", polygons),
                vector("before_faults", "修改前构造图", lines),
                vector("alterations", "获批矿物处理状态", polygons),
                vector("intersections", "当前构造交汇点", points),
            ],
            [
                output(
                    "before_zones",
                    "修改前优先核查远景区",
                    "vector",
                    "before_zones.gpkg",
                ),
                output(
                    "after_zones", "修改后优先核查远景区", "vector", "after_zones.gpkg"
                ),
                output("evidence", "每区实测依据链", "table", "evidence.csv"),
                output("statistics", "前后远景区统计", "table", "statistics.csv"),
            ],
        ),
    }
    for suffix, (name, inputs, outputs) in variants.items():
        directory = Path(__file__).resolve().parent.parent / ("geology-multi-" + suffix)
        manifest = {
            "schemaVersion": 1,
            "identifier": directory.name,
            "name": name,
            "version": "1.0.8",
            "description": name
            + "。依据显式绑定的试用知识和当前输入真实测量，不读取独立评价材料；修改须逐项批准，保留、待裁定、降权和剔除分别记录。",
            "author": "STISP",
            "runtime": "python-geospatial-v1",
            "agent": {"enabled": True},
            "qualityReport": {"file": "quality.json"},
            "inputs": inputs,
            "parameters": parameters,
            "outputs": outputs,
            "timeoutSeconds": 900,
            "deterministic": True,
        }
        for row in manifest["outputs"]:
            if row["kind"] == "vector":
                row["required"] = (
                    row["key"]
                    not in {
                        "faults",
                        "alterations",
                        "final_faults",
                        "final_alterations",
                        "intersections",
                        "before_intersections",
                        "before_zones",
                        "after_zones",
                    }
                    and "issues" not in row["key"]
                )
        if suffix == "prospect":
            for row in manifest["inputs"]:
                if row["key"] in {"alterations", "intersections"}:
                    row["required"] = False
        (directory / "operator.yaml").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (directory / "README.md").write_text(
            "# "
            + name
            + "\n\n使用 `../geology-multi-core/build.py` 构建独立 ZIP。不要只打包本目录，worker 必须包含共享核心。\n\n规则参数来自本场景明确绑定的试用知识及版本；输出保留当次测量、知识引用与算法证据。获批执行必须精确匹配对象、范围、规则版本与输入快照。\n\n所有输出写入当前任务目录；支持空结果。计算使用米制投影，显示沿平台既有坐标转换。\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    create()
