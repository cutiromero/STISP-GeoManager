"""Static package validation. Uploaded Python is never imported by Django."""

import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import PurePosixPath
import re
import stat
import zipfile

import yaml

KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,79}$")
EXTENSIONS = {
    "raster": {".tif", ".tiff"},
    "vector": {".gpkg"},
    "table": {".csv"},
    "image": {".png", ".jpg"},
    "report": {".pdf"},
    "archive": {".zip"},
}


class ComputeError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


@dataclass
class ChecksumVerification:
    cache: dict = field(default_factory=dict)
    reads: int = 0
    reuses: int = 0
    bytes_read: int = 0


_CHECKSUM_VERIFICATION = ContextVar("compute_checksum_verification", default=None)


@contextmanager
def checksum_scope():
    """Reuse unchanged file hashes only within one synchronous operation."""
    current = _CHECKSUM_VERIFICATION.get()
    if current is not None:
        yield current
        return
    current = ChecksumVerification()
    token = _CHECKSUM_VERIFICATION.set(current)
    try:
        yield current
    finally:
        _CHECKSUM_VERIFICATION.reset(token)


def _file_identity(value):
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_mode,
    )


def checksum(path):
    verification = _CHECKSUM_VERIFICATION.get()
    if verification is None or path.is_symlink():
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    identity = _file_identity(path.stat())
    key = (str(path.absolute()), identity)
    if key in verification.cache:
        verification.reuses += 1
        return verification.cache[key]
    with path.open("rb") as stream:
        before = _file_identity(os.fstat(stream.fileno()))
        value = hashlib.file_digest(stream, "sha256").hexdigest()
        after = _file_identity(os.fstat(stream.fileno()))
    if identity != before or before != after or after != _file_identity(path.stat()):
        raise ComputeError("文件在内容校验过程中发生变化，请重新读取", 409)
    verification.reads += 1
    verification.bytes_read += identity[2]
    if len(verification.cache) < 512:
        verification.cache[key] = value
    return value


def clean_text(value, maximum, label, required=True):
    if (
        not isinstance(value, str)
        or len(value.strip()) > maximum
        or (required and not value.strip())
    ):
        raise ComputeError(f"{label}须为1至{maximum}字的文字")
    return value.strip()


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise ComputeError("清单必须是 schemaVersion: 1 的对象")
    result = {}
    for name, maximum in [
        ("identifier", 80),
        ("name", 160),
        ("version", 40),
        ("description", 4000),
        ("author", 160),
    ]:
        result[name] = clean_text(manifest.get(name), maximum, name)
    if not IDENTIFIER.fullmatch(result["identifier"]) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}", result["version"]
    ):
        raise ComputeError("标识或版本只允许规范的字母、数字及分隔符")
    if manifest.get("runtime") != "python-geospatial-v1":
        raise ComputeError("请选择已支持的 python-geospatial-v1 运行环境")
    result.update(
        schemaVersion=1,
        runtime=manifest["runtime"],
        deterministic=manifest.get("deterministic", False) is True,
    )
    if "agent" in manifest:
        agent = manifest["agent"]
        if (
            not isinstance(agent, dict)
            or set(agent) != {"enabled"}
            or type(agent["enabled"]) is not bool
        ):
            raise ComputeError("agent 配置只接受布尔值 enabled")
        result["agent"] = {"enabled": agent["enabled"]}
    if "qualityReport" in manifest:
        quality = manifest["qualityReport"]
        if (
            not isinstance(quality, dict)
            or set(quality) != {"file"}
            or not isinstance(quality["file"], str)
            or not re.fullmatch(
                r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,145}\.json", quality["file"]
            )
        ):
            raise ComputeError("qualityReport 只接受安全单层 JSON 文件名 file")
        result["qualityReport"] = {"file": quality["file"]}
    timeout = manifest.get("timeoutSeconds", 1800)
    if type(timeout) is not int or not 1 <= timeout <= 7200:
        raise ComputeError("timeoutSeconds 必须为1至7200的整数")
    result["timeoutSeconds"] = timeout
    for section in ("inputs", "parameters", "outputs"):
        values = manifest.get(section, [])
        if (
            not isinstance(values, list)
            or len(values) > 30
            or (section in {"inputs", "outputs"} and not values)
        ):
            raise ComputeError(f"{section} 需为列表，输入输出不可为空，每组至多30项")
        seen = set()
        result[section] = []
        for item in values:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("key"), str)
                or not KEY.fullmatch(item["key"])
                or item["key"] in seen
            ):
                raise ComputeError(f"{section} 包含重复或无效 key")
            seen.add(item["key"])
            normalized = dict(
                item,
                label=clean_text(item.get("label"), 160, "label"),
                required=item.get("required", True) is True,
            )
            if section == "inputs":
                if item.get("kind") not in {"raster", "vector", "table"}:
                    raise ComputeError("输入仅支持 raster/vector/table")
                if "minBands" in item and (
                    type(item["minBands"]) is not int
                    or not 1 <= item["minBands"] <= 1024
                ):
                    raise ComputeError("minBands 无效")
                if "geometryTypes" in item and (
                    not isinstance(item["geometryTypes"], list)
                    or not set(item["geometryTypes"])
                    <= {
                        "Point",
                        "MultiPoint",
                        "LineString",
                        "MultiLineString",
                        "Polygon",
                        "MultiPolygon",
                    }
                ):
                    raise ComputeError("geometryTypes 无效")
            elif section == "outputs":
                file = item.get("file", "")
                if (
                    not isinstance(file, str)
                    or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,150}", file)
                    or PurePosixPath(file).suffix
                    not in EXTENSIONS.get(item.get("kind"), set())
                ):
                    raise ComputeError("输出必须是合法的单层文件名，且类型与扩展名匹配")
            else:
                if item.get("type") not in {
                    "integer",
                    "number",
                    "string",
                    "boolean",
                    "enum",
                    "field",
                    "band",
                }:
                    raise ComputeError("参数类型不支持")
                for bound in ("min", "max"):
                    if bound in item and (
                        type(item[bound]) not in {int, float}
                        or not math.isfinite(item[bound])
                    ):
                        raise ComputeError("参数范围须为有限数字")
                if item.get("min", 0) > item.get("max", float("inf")) and "min" in item:
                    raise ComputeError("参数最小值不能大于最大值")
                if item["type"] == "enum" and (
                    not isinstance(item.get("choices"), list)
                    or not item["choices"]
                    or len(item["choices"]) > 100
                    or not all(isinstance(x, str) for x in item["choices"])
                ):
                    raise ComputeError("枚举参数需提供 choices")
                when = item.get("when")
                if when is not None and (
                    not isinstance(when, dict)
                    or set(when) != {"key", "equals"}
                    or when["key"] not in {p["key"] for p in result["parameters"]}
                ):
                    raise ComputeError("条件参数仅允许引用前面的参数并使用 key/equals")
            result[section].append(normalized)
    input_keys = {x["key"] for x in result["inputs"]}
    for p in result["parameters"]:
        if p["type"] in {"field", "band"} and p.get("input") not in input_keys:
            raise ComputeError("字段/波段参数必须关联一个输入")
    files = [x["file"] for x in result["outputs"]]
    if len(files) != len(set(files)):
        raise ComputeError("输出文件名不能重复")
    if result.get("qualityReport", {}).get("file") in files:
        raise ComputeError("质量报告文件名不能与普通输出重复")
    try:
        serialized = json.dumps(result, allow_nan=False)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ComputeError("清单只能包含有限数字、文字、布尔、列表和对象") from exc
    if len(serialized) > 262144:
        raise ComputeError("清单过大")
    return result


def inspect_package(path, extract_to=None):
    if path.stat().st_size > 50 * 1024**2:
        raise ComputeError("算法包压缩大小不能超过50 MiB")
    try:
        with zipfile.ZipFile(path) as archive:
            items = archive.infolist()
            if len(items) > 5000 or sum(i.file_size for i in items) > 500 * 1024**2:
                raise ComputeError("算法包解压规模超限")
            names = set()
            for item in items:
                parts = PurePosixPath(item.filename)
                mode = item.external_attr >> 16
                if (
                    "\\" in item.filename
                    or ":" in item.filename
                    or "\x00" in item.filename
                    or parts.is_absolute()
                    or ".." in parts.parts
                    or any(
                        part.endswith((".", " "))
                        or part.split(".")[0].upper()
                        in {
                            "CON",
                            "PRN",
                            "AUX",
                            "NUL",
                            *[f"COM{i}" for i in range(1, 10)],
                            *[f"LPT{i}" for i in range(1, 10)],
                        }
                        for part in parts.parts
                    )
                    or stat.S_ISLNK(mode)
                    or (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR})
                ):
                    raise ComputeError("算法包含不安全路径或链接")
                folded = item.filename.casefold().rstrip("/")
                if (
                    folded in names
                    or item.flag_bits & 1
                    or item.file_size > max(item.compress_size, 1) * 300
                ):
                    raise ComputeError("算法包包含重复文件、加密项或异常压缩比")
                names.add(folded)
            if not {"operator.yaml", "main.py", "README.md"} <= set(archive.namelist()):
                raise ComputeError("ZIP根目录须包含 operator.yaml、main.py、README.md")
            entry = archive.getinfo("operator.yaml")
            if entry.file_size > 262144:
                raise ComputeError("清单不可超过256 KiB")
            source = archive.read(entry).decode("utf-8")
            if any(
                isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken))
                for token in yaml.scan(source)
            ):
                raise ComputeError("清单不能使用 YAML 锚点或别名")
            manifest = validate_manifest(yaml.safe_load(source))
            if extract_to:
                for item in items:
                    dest = extract_to.joinpath(*PurePosixPath(item.filename).parts)
                    if item.is_dir():
                        dest.mkdir(parents=True, exist_ok=True)
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(item) as src, dest.open("wb") as dst:
                            import shutil

                            shutil.copyfileobj(src, dst)
            return manifest
    except (zipfile.BadZipFile, KeyError, UnicodeError, yaml.YAMLError) as exc:
        raise ComputeError("ZIP或operator.yaml格式无效") from exc
