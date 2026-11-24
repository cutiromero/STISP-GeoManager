"""Task-local edits to the Python files of a published operator."""

import ast
import hashlib
from pathlib import PurePosixPath
from zipfile import ZipFile

from apps.core.storage import app_path
from .packages import ComputeError, checksum

RUNTIME = "python-geospatial-v1"
MAX_SOURCE_BYTES = 256 * 1024
SOURCE_PAGE = 80


def source_file(name):
    return (
        isinstance(name, str)
        and name.endswith(".py")
        and all(
            part not in {"", ".", ".."}
            and part.isascii()
            and all(char.isalnum() or char in "._-" for char in part)
            for part in name.split("/")
        )
    )


def verified_archive(version):
    path = app_path(version.package_path)
    if not path.is_file() or checksum(path) != version.checksum:
        raise ComputeError("请选择校验通过的算子发布包", 409)
    return path


def source_text(archive, name):
    if not source_file(name):
        raise ComputeError("请选择发布包中的 Python 文件")
    try:
        item = archive.getinfo(name)
        if item.file_size > MAX_SOURCE_BYTES:
            raise ComputeError("请选取可读取的 Python 模块")
        return archive.read(item).decode("utf-8")
    except (KeyError, UnicodeError) as error:
        raise ComputeError("请选择源码目录中的 UTF-8 Python 文件") from error


def inspect_source(version, filename=None, offset=0, *, snapshot=None):
    with ZipFile(verified_archive(version)) as archive:
        result = {
            "versionId": version.id,
            "sourceSha256": version.checksum,
            "files": [name for name in archive.namelist() if source_file(name)],
        }
        if snapshot:
            result["copyFiles"] = snapshot["files"]
        if filename:
            text = source_text(archive, filename)
            if snapshot and filename in snapshot["files"]:
                edits = [edit for edit in snapshot["edits"] if edit["file"] == filename]
                files = apply_edits(edits, lambda _: text)
                if file_digests(files)[filename] != snapshot["files"][filename]:
                    raise ComputeError("请选择校验通过的任务副本", 409)
                text = files[filename]
            lines = text.splitlines(keepends=True)
            end = offset + SOURCE_PAGE
            result.update(
                file=filename,
                offset=offset,
                source="".join(lines[offset:end]),
                nextOffset=end if end < len(lines) else None,
            )
        return result


def apply_edits(edits, read):
    files = {}
    for edit in edits:
        filename, before, after = (edit[key] for key in ("file", "before", "after"))
        if not source_file(filename):
            raise ComputeError("请选择发布包中的 Python 文件")
        # The literal match anchors each edit to the source inspected by the agent.
        text = files[filename] if filename in files else read(filename)
        if not before or before == after or text.count(before) != 1:
            raise ComputeError(f"请重新读取 {filename} 并选择一段唯一的上下文", 409)
        files[filename] = text.replace(before, after, 1)
    for filename, text in files.items():
        if len(text.encode()) > MAX_SOURCE_BYTES:
            raise ComputeError(f"请缩小 {filename} 的修改范围")
        try:
            ast.parse(text, filename=filename)
        except (SyntaxError, ValueError) as error:
            raise ComputeError(
                f"{filename} 第 {getattr(error, 'lineno', '?')} 行：{getattr(error, 'msg', str(error))}"
            ) from error
    return files


def file_digests(files):
    return {
        name: hashlib.sha256(source.encode()).hexdigest()
        for name, source in files.items()
    }


def prepare(version, edits):
    if version.manifest.get("runtime") != RUNTIME:
        raise ComputeError("请选择支持 Python 地理计算副本的算子版本")
    with ZipFile(verified_archive(version)) as archive:
        files = apply_edits(edits, lambda name: source_text(archive, name))
    return {
        "sourceSha256": version.checksum,
        "files": file_digests(files),
        "edits": edits,
    }


def materialize(snapshot, version, package):
    if snapshot["sourceSha256"] != version.checksum:
        raise ComputeError("请按当前发布版本重新生成算子副本", 409)
    files = apply_edits(
        snapshot["edits"],
        lambda name: (
            package.joinpath(*PurePosixPath(name).parts).read_bytes().decode("utf-8")
        ),
    )
    if file_digests(files) != snapshot["files"]:
        raise ComputeError("请重新提交算子副本，执行快照校验未通过", 409)
    for name, source in files.items():
        package.joinpath(*PurePosixPath(name).parts).write_bytes(source.encode())
