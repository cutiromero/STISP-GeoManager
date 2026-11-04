"""Bounded, task-scoped bundle uploads using the existing import pipeline."""

from __future__ import annotations

import lzma
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
import zlib
from pathlib import Path, PurePosixPath

from django.core.files import File

from apps.compute.packages import ComputeError
from apps.core.runtime_config import runtime_upload_max_mb

from .workflow_uploads import (
    MAX_FILES,
    RASTER_SUFFIXES,
    TABLE_SUFFIXES,
    VECTOR_SUFFIXES,
    batch_uploads,
    checked_batch,
    require_upload_access,
    store_upload,
    upload_json,
)

MAX_ENTRIES = 512
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
SHAPE_PARTS = {".shp", ".dbf", ".shx", ".prj", ".cpg", ".sbn", ".sbx", ".qix"}


def safe_path(name):
    name = name.replace("\\", "/")
    path = PurePosixPath(name)
    if (
        not name
        or "\x00" in name
        or path.is_absolute()
        or ".." in path.parts
        or re.match(r"^[a-zA-Z]:", name)
    ):
        raise ComputeError("压缩包含不安全路径")
    return path


def ignored(path):
    name = path.name.casefold()
    return (
        "__macosx" in [part.casefold() for part in path.parts]
        or name == ".ds_store"
        or name.startswith(("._", "~$", ".~lock."))
        or name.endswith((".aux.xml", ".shp.xml", ".lock", ".lck", ".sr.lock"))
    )


def extract_bundle(uploaded, root, budget):
    with zipfile.ZipFile(uploaded) as archive:
        entries = archive.infolist()
        budget[0] += len(entries)
        if budget[0] > MAX_ENTRIES:
            raise ComputeError(f"总压缩包最多包含{MAX_ENTRIES}个条目")
        seen, accepted = set(), []
        for entry in entries:
            name = entry.filename
            if not entry.flag_bits & 0x800:
                raw_name = name.encode("cp437")
                for encoding in ("utf-8", "gb18030"):
                    try:
                        name = raw_name.decode(encoding)
                        break
                    except UnicodeDecodeError:
                        continue
            path = safe_path(name)
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode) or (
                stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)
            ):
                raise ComputeError("压缩包不允许符号链接或特殊文件")
            key = str(path).casefold()
            if key in seen:
                raise ComputeError("压缩包含重复路径")
            seen.add(key)
            if entry.flag_bits & 1:
                raise ComputeError("不支持加密压缩包")
            budget[1] += entry.file_size
            if budget[1] > budget[2]:
                raise ComputeError("压缩包累计解压大小超过上传上限")
            if not entry.is_dir() and not ignored(path):
                accepted.append((entry, path))
        for entry, relative in accepted:
            target = root.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, target.open("wb") as output:
                copied = 0
                while chunk := source.read(1024 * 1024):
                    copied += len(chunk)
                    if copied > entry.file_size:
                        raise ComputeError("压缩包条目实际大小不符")
                    output.write(chunk)
        return [root.joinpath(*path.parts) for _, path in accepted]


def materialize(paths, root):
    groups, singles = {}, []
    for path in paths:
        if path.suffix.lower() in SHAPE_PARTS:
            groups.setdefault(str(path.with_suffix("")).casefold(), []).append(path)
        else:
            singles.append(path)
    for parts in groups.values():
        main = next((part for part in parts if part.suffix.lower() == ".shp"), None)
        if main is None:
            singles.append(parts[0])
            continue
        target = root / ("shape-" + uuid.uuid4().hex + ".zip")
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for part in parts:
                archive.write(part, main.stem + part.suffix.lower())
        singles.append((target, main.with_suffix(".zip").name))
    return [(item, item.name) if isinstance(item, Path) else item for item in singles]


def store_batch(user, project, files, batch_id):
    checked_batch(batch_id)
    require_upload_access(user, project)
    if batch_uploads(user, batch_id).filter(workflow__isnull=False).exists():
        raise ComputeError("该批次资料已用于任务，请新建批次", 409)
    if not files or len(files) > MAX_ENTRIES:
        raise ComputeError("请选择1至512个文件")
    limit = min(runtime_upload_max_mb() * 1024 * 1024, MAX_EXPANDED_BYTES)
    if sum(file.size for file in files) > limit:
        raise ComputeError("上传文件累计大小超过上传上限")
    result = {"items": [], "errors": []}
    budget = [0, 0, limit]
    with tempfile.TemporaryDirectory(prefix="geomanager-bundle-") as directory:
        root = Path(directory)
        loose = []
        candidates = []
        for index, uploaded in enumerate(files):
            try:
                relative = safe_path(uploaded.name)
                if ignored(relative):
                    continue
                if relative.suffix.lower() == ".zip":
                    folder = root / f"archive-{index}"
                    paths = extract_bundle(uploaded, folder, budget)
                    materials = materialize(paths, root)
                    if not materials:
                        raise ComputeError("压缩包没有可用资料")
                    candidates.extend(materials)
                else:
                    budget[0] += 1
                    budget[1] += uploaded.size
                    if budget[0] > MAX_ENTRIES or budget[1] > limit:
                        raise ComputeError("资料累计条目数或大小超过上传上限")
                    target = root / "loose" / relative.name
                    target.parent.mkdir(exist_ok=True)
                    if target.exists():
                        raise ComputeError("上传文件含重复名称")
                    with target.open("wb") as output:
                        shutil.copyfileobj(uploaded, output)
                    loose.append(target)
            except (
                ComputeError,
                zipfile.BadZipFile,
                RuntimeError,
                OSError,
                EOFError,
                ValueError,
                zlib.error,
                lzma.LZMAError,
            ) as exc:
                result["errors"].append(
                    {"fileName": uploaded.name, "detail": str(exc)[:300]}
                )
        candidates.extend(materialize(loose, root))
        for path, name in candidates:
            try:
                if path.suffix.lower() in SHAPE_PARTS:
                    raise ComputeError("Shapefile缺少.shp主文件")
                if path.suffix.lower() == ".zip" and path.parent != root:
                    raise ComputeError("总压缩包内不支持嵌套ZIP，请先解开内层压缩包")
                if (
                    path.suffix.lower()
                    not in VECTOR_SUFFIXES | TABLE_SUFFIXES | RASTER_SUFFIXES
                ):
                    raise ComputeError("不支持的资料类型")
                if batch_uploads(user, batch_id).count() >= MAX_FILES:
                    raise ComputeError(f"每个任务最多上传{MAX_FILES}份资料")
                with path.open("rb") as source:
                    upload = store_upload(
                        user, project, File(source, name=name), batch_id
                    )
                result["items"].append(upload_json(upload))
            except (ComputeError, ValueError, OSError, zipfile.BadZipFile) as exc:
                result["errors"].append({"fileName": name, "detail": str(exc)[:300]})
    return result
