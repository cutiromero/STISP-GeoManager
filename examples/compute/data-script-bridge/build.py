"""Build the single generic interpreter capability, not conversion templates."""

from pathlib import Path
import io
import json
import zipfile
import runpy

# ==================== CONFIGURATION ====================
ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / ".runtime/input-adapter-packages/input-data-script-bridge.zip"
VERSION = "1.1.0"
MAX_SOURCES_PER_TYPE = 5
FILES = {
    "vector": "prepared.gpkg",
    "raster": "prepared.tif",
    "table": "prepared.csv",
    "gene": "prepared.fasta",
    "document": "prepared.txt",
    "image": "prepared.png",
}
# =======================================================


def manifest():
    ports = {
        kind: [f"source_{kind}_{index}" for index in range(1, MAX_SOURCES_PER_TYPE + 1)]
        for kind in FILES
    }
    value = {
        "schemaVersion": 1,
        "identifier": "input-data-script-bridge",
        "name": "智能资料衔接脚本",
        "version": VERSION,
        "description": "由业务流智能体根据实际来源编写简短Python，受限运行并生成派生输入；原始资料只读。",
        "author": "STISP",
        "runtime": "python-data-script-v1",
        "agent": {"enabled": True},
        "inputs": [
            {
                "key": key,
                "label": kind + "来源" + str(index),
                "kind": kind,
                "required": False,
            }
            for kind, names in ports.items()
            for index, key in enumerate(names, 1)
        ],
        "parameters": [
            {
                "key": "code",
                "label": "Python资料衔接脚本",
                "type": "string",
                "required": True,
                "maxLength": 16000,
                "help": "仅生成声明的派生结果；业务流通常自动编写和填入。",
            },
            {
                "key": "target_type",
                "label": "目标资料类型",
                "type": "enum",
                "choices": list(FILES),
                "default": "table",
            },
            {
                "key": "target_contract",
                "label": "冻结目标规范（JSON）",
                "type": "string",
                "required": True,
                "maxLength": 16000,
            },
        ],
        "outputs": [
            {
                "key": "prepared_" + kind,
                "label": "衔接结果（" + kind + "）",
                "kind": kind,
                "file": file,
                "required": False,
            }
            for kind, file in FILES.items()
        ],
        "inputScriptBridge": {
            "inputPorts": ports,
            "outputPorts": {kind: "prepared_" + kind for kind in FILES},
            "codeParameter": "code",
            "targetParameter": "target_type",
            "contractParameter": "target_contract",
            "policyVersion": 1,
        },
        "qualityReport": {"file": "quality.json"},
        "timeoutSeconds": 120,
        "deterministic": False,
    }
    enrich = runpy.run_path(str(ROOT / "examples/compute/operator_metadata.py"))[
        "enrich"
    ]
    enrich(
        value,
        "convert",
        avoid_when="不用于绕过文件权限、网络限制、人工批准或替代冻结科学算子；代码仅在专用受限解释器执行。",
    )
    value["errors"] = [
        {
            "code": "SCRIPT_FAILED",
            "meaning": "受限资料衔接脚本未通过执行或目标检查",
            "remedy": "human_review",
            "precondition": "来源、代码和冻结目标规范须一致；运行机须具备内核隔离能力",
        }
    ]
    value["selfTests"] = [
        {
            "name": "表格脚本衔接",
            "fixture": "selftest/smoke.json",
            "expect": {"files": {"prepared.csv": {"rows": 1, "columns": ["name"]}}},
        }
    ]
    return value


def build():
    files = {
        "operator.yaml": json.dumps(manifest(), ensure_ascii=False, indent=2).encode(),
        "main.py": b'def run(context):\n    raise RuntimeError("Use the platform-owned confined script interpreter")\n',
        "README.md": "业务流通用数据衔接能力。Python代码由Agent按实际输入编写；固定流程、科学算子、数据权限和人工批准不被改变。\n".encode(),
    }
    files["selftest/smoke.json"] = (
        Path(__file__).parent / "smoke.selftest.json"
    ).read_bytes()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            item = zipfile.ZipInfo(name, (2026, 11, 10, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(item, data)
    return buffer.getvalue()


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(build())
    print(str(OUTPUT))
