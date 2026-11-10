"""Build portable input-adaptation packages for the ordinary compute registry."""

from pathlib import Path
import io
import json
import zipfile

# ==================== CONFIGURATION ====================
ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / ".runtime/input-adapter-packages"
VERSION = "1.0.0"
SPECS = {
    "input-vector-class-masks": (
        "分类矢量栅格化",
        "vector",
        "raster",
        "class_mask_stack_v1",
        "vector_masks.py",
    ),
    "input-raster-class-masks": (
        "栅格类别规范化",
        "raster",
        "raster",
        "class_mask_stack_v1",
        "raster_masks.py",
    ),
    "input-raster-band-statistics": (
        "栅格波段统计转表",
        "raster",
        "table",
        "raster_band_statistics_v1",
        "raster_statistics.py",
    ),
}
# =======================================================


def manifest(identifier):
    name, source, target, semantics, _ = SPECS[identifier]
    params = []
    capability = {
        "inputKey": "source",
        "outputKey": "prepared",
        "sourceKind": source,
        "targetKind": target,
        "targetSemantics": semantics,
        "description": name + "，只生成派生结果，不修改来源。",
    }
    if source == "vector":
        params = [
            {
                "key": "category_field",
                "label": "类别名称字段",
                "type": "field",
                "input": "source",
            },
            {
                "key": "resolution_m",
                "label": "输出分辨率（米）",
                "type": "number",
                "default": 100,
                "min": 10,
                "max": 1000,
            },
            {
                "key": "target_epsg",
                "label": "目标EPSG（0自动选择米制投影）",
                "type": "integer",
                "default": 0,
                "min": 0,
                "max": 999999,
            },
        ]
        capability.update(
            fieldHints={
                "category_field": [
                    "mineral",
                    "alteration",
                    "category",
                    "矿物",
                    "蚀变",
                    "class",
                    "类别",
                    "name",
                    "名称",
                ]
            },
            fieldTargets={"category_field": "mineral"},
        )
    elif target == "raster":
        params = [
            {
                "key": "label",
                "label": "单波段类别名称",
                "type": "string",
                "default": "类别",
            },
            {
                "key": "class_labels",
                "label": "非0/1分类值的真实名称映射（JSON）",
                "type": "string",
                "default": "{}",
            },
        ]
        capability["metadataParameters"] = {"label": "sourceName"}
    else:
        params = [
            {
                "key": "band",
                "label": "统计波段（0表示全部）",
                "type": "integer",
                "default": 0,
                "min": 0,
                "max": 1024,
            }
        ]
        capability["outputFields"] = ["band", "name", "count", "min", "max", "mean"]
    return {
        "schemaVersion": 1,
        "identifier": identifier,
        "name": name,
        "version": VERSION,
        "description": capability["description"],
        "author": "STISP",
        "runtime": "python-geospatial-v1",
        "agent": {"enabled": True},
        "qualityReport": {"file": "quality.json"},
        "inputs": [{"key": "source", "label": "原始来源资料", "kind": source}],
        "parameters": params,
        "outputs": [
            {
                "key": "prepared",
                "label": name + "结果",
                "kind": target,
                "file": "masks.tif" if target == "raster" else "statistics.csv",
            }
        ],
        "inputAdapter": capability,
        "timeoutSeconds": 900,
        "deterministic": True,
    }


def build(identifier):
    data = {
        "main.py": (HERE / SPECS[identifier][4]).read_bytes(),
        "operator.yaml": json.dumps(
            manifest(identifier), ensure_ascii=False, indent=2
        ).encode(),
        "README.md": (manifest(identifier)["description"] + "\n").encode(),
        "data_adapters.py": (ROOT / "backend/apps/core/data_adapters.py").read_bytes(),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(data.items()):
            entry = zipfile.ZipInfo(name, date_time=(2026, 11, 10, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, raw)
    return output.getvalue()


if __name__ == "__main__":
    DEFAULT_OUTPUT.mkdir(parents=True, exist_ok=True)
    for identifier in SPECS:
        (DEFAULT_OUTPUT / (identifier + ".zip")).write_bytes(build(identifier))
    print("Built " + str(len(SPECS)) + " input adapter packages")
