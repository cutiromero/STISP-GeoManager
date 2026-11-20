"""Rebuild the verified archive Apply package with boundary-only dissolution."""

from hashlib import sha256
import io
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

# 用户配置：可信基包和输出位置；包内归档证据不写入 Git。
BASE_PACKAGE = Path(
    "/Users/xintao/Project/时空智能遥感平台/运维说明/五龙沟岩性测试图简化-20261119/候选算子/geology-multi-apply-1.7.3.zip"
)
OUTPUT_PACKAGE = (
    Path(__file__).resolve().parents[3]
    / ".runtime/logic-review-geometry-20261120/geology-multi-apply-1.7.4.zip"
)
BASE_SHA256 = "c96538a47785abaf43956bde02f95f123770d460ef887bd55181f60fdc14a0c2"
NEW_VERSION = "1.7.4"
SOURCE = Path(__file__).resolve().parents[1] / "geology-multi-core/archive_dissolve.py"
HOOK = '    corrected, extra = archive.apply(corrected, [row for row in operations if row["feature_id"] in archive.items])\n'


def build(base: bytes, module: bytes) -> bytes:
    if sha256(base).hexdigest() != BASE_SHA256:
        raise ValueError("基包不是已冻结的 1.7.3，不能替换不同版本或证据")
    with ZipFile(io.BytesIO(base)) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(files["operator.yaml"])
    if (
        manifest["identifier"] != "geology-multi-apply"
        or manifest["version"] != "1.7.3"
    ):
        raise ValueError("基包算子或版本错误")
    main = files["main.py"].decode("utf-8")
    if main.count(HOOK) != 1:
        raise ValueError("无法精确找到既有归档审批执行入口")
    entry_import = "from archive_overlay import ArchiveReview\n"
    if main.count(entry_import) != 1:
        raise ValueError("无法定位归档算子依赖")
    main = main.replace(
        entry_import,
        entry_import + "from archive_dissolve import dissolve_archive_additions\n",
    ).replace(
        HOOK, HOOK + "    corrected = dissolve_archive_additions(corrected, extra)\n"
    )
    manifest["version"] = NEW_VERSION
    files["main.py"] = main.encode("utf-8")
    files["archive_dissolve.py"] = module
    files["operator.yaml"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode()
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = ZipInfo(name, date_time=(2026, 11, 20, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, content)
    return output.getvalue()


def main():
    package = build(BASE_PACKAGE.read_bytes(), SOURCE.read_bytes())
    OUTPUT_PACKAGE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PACKAGE.write_bytes(package)
    print(sha256(package).hexdigest(), OUTPUT_PACKAGE)


if __name__ == "__main__":
    main()
