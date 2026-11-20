"""Build a matched whole-feature Check/Apply revision from the published vector pair."""

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


@dataclass(frozen=True)
class Baseline:
    identifier: str
    version: str
    sha256: str


# 配置：仅引用已发布的整斑矢量包；下载或重建包时必须匹配登记摘要。
CORE = Path(__file__).resolve().parent
BASELINES = CORE.parents[2] / ".runtime/vector-restore-20261120"
OUTPUT = CORE.parents[2] / ".runtime/vector-context-v2-20261120/packages"
NEW_VERSION = "1.8.0"
INPUTS = (
    Baseline(
        "geology-multi-check",
        "1.7.2",
        "8e1c69efeb7646182962fc602dacbf95a0a32f765a92c9d909457f748ba604f2",
    ),
    Baseline(
        "geology-multi-apply",
        "1.7.5",
        "f57ec46ab7eaf4d81a2772105d997cd39ec9d3547d89c28c8f3dce9d6c75b446",
    ),
)
MODULES = ("multi_context.py", "multi_checks.py")
DESCRIPTIONS = {
    "geology-multi-check": "按原始矢量图斑的真实共边、形态、同类连续性和构造证据列出待核查疑点。单元组合及时代仅作为判读依据，不是硬门槛。",
    "geology-multi-apply": "以同版矢量规则复核冻结疑点，只按用户批准整斑改类、融合共边，不改变原件，不按像元裁切岩性要素。",
}


def build(source, raw):
    if sha256(raw).hexdigest() != source.sha256:
        raise ValueError(f"已发布算子 {source.identifier} {source.version} 的摘要不符")
    with ZipFile(BytesIO(raw)) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(files["operator.yaml"])
    if (manifest["identifier"], manifest["version"]) != (
        source.identifier,
        source.version,
    ):
        raise ValueError("已发布算子的标识或版本不符")
    if not set(MODULES) <= files.keys():
        raise ValueError("基线算子包缺少已发布的矢量检查模块")
    for name in MODULES:
        files[name] = (CORE / name).read_bytes()
    manifest.update(version=NEW_VERSION, description=DESCRIPTIONS[source.identifier])
    files["operator.yaml"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode()
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            member = ZipInfo(name, date_time=(2026, 11, 20, 0, 0, 0))
            member.compress_type = ZIP_DEFLATED
            archive.writestr(member, data)
    return output.getvalue()


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for source in INPUTS:
        name = f"{source.identifier}-{source.version}.zip"
        result = build(source, (BASELINES / name).read_bytes())
        destination = OUTPUT / f"{source.identifier}-{NEW_VERSION}.zip"
        if destination.is_file():
            if destination.read_bytes() != result:
                raise ValueError(f"不覆盖已有的不同构建包：{destination}")
        else:
            destination.write_bytes(result)
        print(sha256(result).hexdigest(), destination)


if __name__ == "__main__":
    main()
