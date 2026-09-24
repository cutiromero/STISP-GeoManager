"""Validate downloadable multi-file outputs without extracting them."""

from pathlib import PurePosixPath
import stat
import zipfile

from .packages import ComputeError


def inspect_archive(path, limit):
    try:
        with zipfile.ZipFile(path) as archive:
            items = archive.infolist()
            if not items or len(items) > 3000:
                raise ComputeError("结果包须包含1至3000个文件")
            if sum(item.file_size for item in items) > limit:
                raise ComputeError("结果包解压后的总大小超过平台限制")
            seen = set()
            for item in items:
                name = PurePosixPath(item.filename)
                mode = item.external_attr >> 16
                if (
                    len(name.parts) != 1
                    or name.is_absolute()
                    or name.name in {".", ".."}
                    or "\\" in item.filename
                    or ":" in item.filename
                    or "\x00" in item.filename
                    or item.filename.casefold() in seen
                    or item.is_dir()
                    or stat.S_ISLNK(mode)
                    or item.flag_bits & 1
                ):
                    raise ComputeError("结果包包含不安全文件名、链接或重复项")
                seen.add(item.filename.casefold())
            if archive.testzip() is not None:
                raise ComputeError("结果包文件校验失败")
            return {
                "format": "ZIP",
                "files": [item.filename for item in items],
                "uncompressedBytes": sum(item.file_size for item in items),
            }
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise ComputeError("结果包损坏或无法读取") from exc
