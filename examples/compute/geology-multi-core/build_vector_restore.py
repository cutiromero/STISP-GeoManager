"""Restore the frozen vector entry points, preserving current input contracts."""

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


@dataclass(frozen=True)
class Restore:
    original: str
    original_sha256: str
    current: str
    current_sha256: str
    release: str
    description: str


# 配置：所需旧包通过平台算子登记下载，必须和已发布的 SHA-256 一致。
PACKAGE_DIR = Path(__file__).resolve().parents[3] / ".runtime/vector-restore-20261120"
RESTORE = {
    "check": Restore(
        "1.5.1",
        "370cf9628793c1386361161d05521495690b48d67739178fe34f311c3e8d033a",
        "1.7.1",
        "2c97c241dcaf6961d25c3fd6b9645a05d6cbfab897cf1ab5eba0590ad61f31d8",
        "1.7.2",
        "按岩性矢量原要素的单元属性、接触邻域及构造关系检查；同单元共边整理和整斑改类分别核查，保留原要素编号。蚀变仍沿用其类别资料协议。",
    ),
    "apply": Restore(
        "1.5.1",
        "97a04f5ad5fdf774ae2e37be1fcb8a716468a3a62fedb4eebd5d40621a5233e1",
        "1.7.3",
        "c96538a47785abaf43956bde02f95f123770d460ef887bd55181f60fdc14a0c2",
        "1.7.5",
        "按冻结批准执行整斑岩性属性处置及同单元矢量共边融合。禁止用像元掩膜拆分岩性要素，记录承接对象、实际改动面积和去除接边；原件保持不变。",
    ),
}


def _files(raw, expected, identifier, version):
    if sha256(raw).hexdigest() != expected:
        raise ValueError(f"算子 {identifier} {version} 的源包摘要不符")
    with ZipFile(BytesIO(raw)) as archive:
        result = {entry.filename: archive.read(entry) for entry in archive.infolist()}
    manifest = json.loads(result["operator.yaml"])
    if (manifest["identifier"], manifest["version"]) != (identifier, version):
        raise ValueError("算子源包的清单不匹配")
    return result, manifest


def build(identifier, spec, original, current):
    prior, _ = _files(original, spec.original_sha256, identifier, spec.original)
    files, manifest = _files(current, spec.current_sha256, identifier, spec.current)
    # The only retained implementation difference is a verified spatial predicate
    # optimization used by mineral rasters. Do not import archive entry points or data.
    vector = {name: files[name] for name in prior}
    vector["main.py"] = prior["main.py"]
    for name, contents in vector.items():
        if name not in {"multi_grid.py", "operator.yaml"} and contents != prior[name]:
            raise ValueError(f"历史矢量代码不一致：{name}")
    manifest.update(version=spec.release, description=spec.description)
    vector["operator.yaml"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode()
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, contents in sorted(vector.items()):
            info = ZipInfo(name, date_time=(2026, 11, 20, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, contents)
    return output.getvalue()


def main():
    for stage, spec in RESTORE.items():
        identifier = "geology-multi-" + stage
        source = PACKAGE_DIR / f"{identifier}-{spec.original}.zip"
        current = PACKAGE_DIR / f"{identifier}-{spec.current}.zip"
        destination = PACKAGE_DIR / f"{identifier}-{spec.release}.zip"
        result = build(identifier, spec, source.read_bytes(), current.read_bytes())
        destination.write_bytes(result)
        print(sha256(result).hexdigest(), destination)


if __name__ == "__main__":
    main()
