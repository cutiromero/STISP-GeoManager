from __future__ import annotations

import hashlib
import json
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

from apps.core.runtime_config import (
    RuntimeConfigError,
    runtime_max_raster_side_pixels,
    runtime_upload_max_mb,
)
from apps.core.storage import raster_source_path
from apps.raster.services.constants import RASTER_EXTENSIONS
from apps.raster.services.categorical import (
    categorical_class_entries,
    is_categorical_metadata,
)
from apps.raster.services.exceptions import RasterImportError
from apps.raster.services.gdal_ops import gdalinfo_json
from apps.raster.services.geo_utils import bounds_4326_from_gdalinfo
from apps.raster.services.rules_engine import default_raster_rules
from apps.raster.services.serializers import compact_raster_metadata


ENVI_DATA_EXTENSIONS = {".dat", ".bsq", ".bil", ".bip"}
HEADER_EXTENSION = ".hdr"
ALLOWED_COMPANION_SUFFIXES = {".hdr", ".rrd", ".ovr", ".xml"}


def preview_uploaded_raster_package(
    uploaded_files: Iterable[Any], primary_file_name: str = ""
) -> dict[str, Any]:
    files = _normalized_uploads(uploaded_files)
    _validate_total_size(files)
    primary_name = _select_primary_file(files, primary_file_name)
    _validate_package_dependencies(files, primary_name)

    with tempfile.TemporaryDirectory(prefix="raster-preview-") as tmpdir:
        root = Path(tmpdir)
        for name, uploaded in files.items():
            _write_uploaded_file(uploaded, root / name)
        primary_path = root / primary_name
        _validate_vrt_references(primary_path, set(files))
        info = gdalinfo_json(primary_path, calculate_statistics=True)
        _validate_pixel_size(info)

    source_format = str(info.get("driverShortName") or "")
    raster_kind = infer_raster_kind(info)
    rules = suggested_default_rules(info, primary_name)
    warnings = _preview_warnings(info)
    return {
        "primaryFileName": primary_name,
        "sourceFormat": source_format,
        "files": source_manifest(files, primary_name),
        "metadata": compact_raster_metadata(info),
        "bounds4326": bounds_4326_from_gdalinfo(info),
        "defaultRules": rules,
        "suggestedName": Path(primary_name).stem,
        "rasterKind": raster_kind,
        "resampling": default_resampling(raster_kind),
        "warnings": warnings,
    }


def store_uploaded_raster_package(
    uploaded_files: Iterable[Any], primary_file_name: str = ""
) -> tuple[Path, list[dict[str, Any]], str]:
    files = _normalized_uploads(uploaded_files)
    _validate_total_size(files)
    primary_name = _select_primary_file(files, primary_file_name)
    _validate_package_dependencies(files, primary_name)

    package_id = uuid.uuid4().hex
    package_relative = f"uploaded/{package_id}"
    package_root = raster_source_path(package_relative)
    package_root.mkdir(parents=True, exist_ok=False)
    written: list[Path] = []
    try:
        for name, uploaded in files.items():
            target = package_root / name
            _write_uploaded_file(uploaded, target)
            written.append(target)
        primary_path = package_root / primary_name
        _validate_vrt_references(primary_path, set(files))
        info = gdalinfo_json(primary_path)
        _validate_pixel_size(info)
        manifest = source_manifest(files, primary_name, stored_root=package_root)
        manifest_path = package_root / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "primaryFileName": primary_name,
                    "sourceFormat": str(info.get("driverShortName") or ""),
                    "files": manifest,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return primary_path, manifest, _sha256(primary_path)
    except Exception:
        for path in reversed(written):
            path.unlink(missing_ok=True)
        raise


def source_manifest(
    files: dict[str, Any],
    primary_name: str,
    *,
    stored_root: Path | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    referenced_names = _vrt_reference_names(
        (stored_root / primary_name) if stored_root else None
    )
    for name, uploaded in files.items():
        role = _asset_role(name, primary_name, referenced_names)
        items.append(
            {
                "name": name,
                "size": int(getattr(uploaded, "size", 0) or 0),
                "role": role,
            }
        )
    return sorted(items, key=lambda item: (item["role"] != "primary", item["name"]))


def infer_raster_kind(info: dict[str, Any]) -> str:
    bands = info.get("bands") or []
    if len(bands) > 1:
        return "imagery"
    if is_categorical_metadata(info):
        return "categorical"
    band = bands[0] if bands else {}
    data_type = str(band.get("type") or "").lower()
    if "float" in data_type:
        return "continuous"
    return "continuous"


def default_resampling(raster_kind: str) -> str:
    return "nearest" if raster_kind == "categorical" else "bilinear"


def suggested_default_rules(
    info: dict[str, Any], primary_file_name: str = ""
) -> dict[str, Any]:
    rules = default_raster_rules(info)
    classes = categorical_class_entries(info)
    if infer_raster_kind(info) == "categorical" and classes:
        rules = {
            **rules,
            "mode": "unique",
            "bands": [1],
            "stretch": {**rules["stretch"], "enabled": False},
            "uniqueValues": classes,
        }
    band_count = len(info.get("bands") or [])
    if band_count >= 8 and "worldview" in primary_file_name.lower():
        rules = {**rules, "mode": "rgb", "bands": [5, 3, 2]}
    return rules


def _normalized_uploads(uploaded_files: Iterable[Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    names_lower: set[str] = set()
    for uploaded in uploaded_files:
        raw_name = str(getattr(uploaded, "name", "") or "").replace("\\", "/")
        name = Path(raw_name).name
        if not name or name in {".", ".."}:
            raise RasterImportError("栅格数据包包含无效文件名")
        lowered = name.lower()
        if lowered in names_lower:
            raise RasterImportError(f"栅格数据包包含重复文件名：{name}")
        suffix = Path(lowered).suffix
        if suffix not in RASTER_EXTENSIONS and suffix not in ALLOWED_COMPANION_SUFFIXES:
            raise RasterImportError(f"不支持的数据包文件：{name}")
        names_lower.add(lowered)
        result[name] = uploaded
    if not result:
        raise RasterImportError("请至少上传一个栅格文件")
    return result


def _select_primary_file(files: dict[str, Any], requested: str) -> str:
    if requested:
        requested_name = Path(requested.replace("\\", "/")).name
        matched = next(
            (name for name in files if name.lower() == requested_name.lower()), None
        )
        if not matched:
            raise RasterImportError(f"主栅格文件不在上传数据包中：{requested_name}")
        if Path(matched).suffix.lower() not in RASTER_EXTENSIONS:
            raise RasterImportError(f"所选主文件不是支持的栅格数据：{matched}")
        return matched

    candidates = [
        name for name in files if Path(name).suffix.lower() in RASTER_EXTENSIONS
    ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise RasterImportError("数据包中没有可识别的栅格主文件")
    raise RasterImportError("数据包包含多个栅格主文件，请明确选择主文件")


def _validate_package_dependencies(files: dict[str, Any], primary_name: str) -> None:
    extension = Path(primary_name).suffix.lower()
    if extension not in ENVI_DATA_EXTENSIONS:
        return
    expected_header = f"{Path(primary_name).stem}.hdr".lower()
    available = {name.lower() for name in files}
    if expected_header not in available:
        raise RasterImportError(
            f"ENVI 栅格缺少配套头文件：请同时上传 {Path(primary_name).stem}.hdr"
        )


def _validate_vrt_references(primary_path: Path, available_names: set[str]) -> None:
    if primary_path.suffix.lower() != ".vrt":
        return
    try:
        root = ET.parse(primary_path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise RasterImportError("VRT 文件不是有效 XML") from exc
    available_lower = {name.lower() for name in available_names}
    missing: list[str] = []
    for node in root.iter("SourceFilename"):
        reference = (node.text or "").strip().replace("\\", "/")
        path = Path(reference)
        if (
            not reference
            or path.is_absolute()
            or ".." in path.parts
            or "://" in reference
            or len(path.parts) != 1
        ):
            raise RasterImportError("VRT 只能引用数据包内同目录的相对文件")
        if path.name.lower() not in available_lower:
            missing.append(path.name)
    if missing:
        raise RasterImportError(f"VRT 缺少引用文件：{', '.join(sorted(set(missing)))}")


def _vrt_reference_names(primary_path: Path | None) -> set[str]:
    if (
        not primary_path
        or primary_path.suffix.lower() != ".vrt"
        or not primary_path.exists()
    ):
        return set()
    try:
        root = ET.parse(primary_path).getroot()
    except (ET.ParseError, OSError):
        return set()
    return {
        Path((node.text or "").strip().replace("\\", "/")).name.lower()
        for node in root.iter("SourceFilename")
        if (node.text or "").strip()
    }


def _asset_role(name: str, primary_name: str, referenced_names: set[str]) -> str:
    if name == primary_name:
        return "primary"
    if Path(name).suffix.lower() == HEADER_EXTENSION:
        return "header"
    if name.lower() in referenced_names:
        return "referenced"
    return "auxiliary"


def _validate_total_size(files: dict[str, Any]) -> None:
    try:
        upload_max_mb = runtime_upload_max_mb()
    except RuntimeConfigError as exc:
        raise RasterImportError(str(exc)) from exc
    total_size = sum(int(getattr(file, "size", 0) or 0) for file in files.values())
    if total_size > upload_max_mb * 1024 * 1024:
        raise RasterImportError(f"栅格数据包总大小不能超过 {upload_max_mb} MB")


def _validate_pixel_size(info: dict[str, Any]) -> None:
    try:
        max_side_pixels = runtime_max_raster_side_pixels()
    except RuntimeConfigError as exc:
        raise RasterImportError(str(exc)) from exc
    size = info.get("size")
    if not isinstance(size, list | tuple) or len(size) < 2:
        raise RasterImportError("无法读取栅格像素尺寸")
    width, height = int(size[0]), int(size[1])
    if width > max_side_pixels or height > max_side_pixels:
        raise RasterImportError(
            f"栅格单边长度不能超过 {max_side_pixels} 像素，当前为 {width} x {height}"
        )


def _preview_warnings(info: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    coordinate_system = info.get("coordinateSystem") or {}
    if not coordinate_system:
        warnings.append("源栅格缺少坐标系，当前版本不会自动猜测 CRS")
    bands = info.get("bands") or []
    if len(bands) > 1 and not any(band.get("description") for band in bands):
        warnings.append("多波段影像缺少波段语义，请确认 RGB 波段组合")
    return warnings


def _write_uploaded_file(uploaded: Any, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(uploaded, "seek"):
        uploaded.seek(0)
    with target.open("wb") as output:
        if hasattr(uploaded, "chunks"):
            for chunk in uploaded.chunks():
                output.write(chunk)
        else:
            output.write(uploaded.read())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
