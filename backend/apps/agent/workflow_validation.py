"""Independent evaluation files, isolated from workflow/model execution inputs."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

from apps.compute.access import permission
from apps.compute.models import ComputeTask
from apps.compute.packages import ComputeError
from apps.core.storage import app_path

KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
PRIVATE_PATH = re.compile(
    r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]|(?<![:/])/(?:root|home|tmp|Users|mnt|var|private|Volumes)/"
)
TYPES = {
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".txt": "text/plain",
}
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
PREVIEW_LIMIT = 200_000


def _bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def validation_directory(workflow) -> Path:
    return app_path("workflow-validations") / str(workflow.id)


def _text(value: object, maximum: int = 6000) -> str:
    if not isinstance(value, str) or len(value) > maximum or PRIVATE_PATH.search(value):
        raise ComputeError("评价文字无效或含内部文件路径，请整理为公开展示内容", 400)
    return value


def _summary(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) != {"scope", "summary", "sections"}:
        raise ComputeError("评价摘要仅支持 scope、summary 和 sections", 400)
    sections = value["sections"]
    if not isinstance(sections, list) or len(sections) > 40:
        raise ComputeError("评价分项格式无效", 400)
    result, seen = [], set()
    for section in sections:
        if not isinstance(section, dict) or set(section) != {
            "key",
            "title",
            "summary",
            "columns",
            "rows",
        }:
            raise ComputeError("评价分项字段无效", 400)
        key = section["key"]
        if not isinstance(key, str) or not KEY.fullmatch(key) or key in seen:
            raise ComputeError("评价分项键无效或重复", 400)
        seen.add(key)
        columns, rows = section["columns"], section["rows"]
        if (
            not isinstance(columns, list)
            or not 1 <= len(columns) <= 30
            or not isinstance(rows, list)
            or len(rows) > 10000
        ):
            raise ComputeError("评价表格规模或格式无效", 400)
        fields, normalized = set(), []
        for column in columns:
            if not isinstance(column, dict) or set(column) != {"key", "label"}:
                raise ComputeError("评价表格列无效", 400)
            name = column["key"]
            if not isinstance(name, str) or not KEY.fullmatch(name) or name in fields:
                raise ComputeError("评价表格列键无效或重复", 400)
            fields.add(name)
            normalized.append({"key": name, "label": _text(column["label"], 200)})
        for row in rows:
            if not isinstance(row, dict) or set(row) - fields:
                raise ComputeError("评价统计行字段无效", 400)
            for item in row.values():
                if isinstance(item, str):
                    _text(item)
                elif item is not None and (
                    type(item) not in (bool, int, float)
                    or (isinstance(item, float) and not math.isfinite(item))
                ):
                    raise ComputeError("评价统计仅支持文本、有限数值、布尔或空值", 400)
        result.append(
            {
                "key": key,
                "title": _text(section["title"], 200),
                "summary": _text(section["summary"]),
                "columns": normalized,
                "rows": rows,
            }
        )
    return {
        "scope": _text(value["scope"]),
        "summary": _text(value["summary"]),
        "sections": result,
    }


def _binding(workflow) -> dict:
    task_ids = workflow.steps.exclude(compute_task_id=None).values_list(
        "compute_task_id", flat=True
    )
    tasks = (
        ComputeTask.objects.filter(id__in=task_ids)
        .select_related("version")
        .order_by("id")
    )
    return {
        "workflowId": str(workflow.id),
        "ownerId": workflow.owner_id,
        "projectId": workflow.project_tag_id,
        "planHash": workflow.plan_hash,
        "inputSnapshots": workflow.plan.get("inputSnapshots", {}),
        "inputs": workflow.plan.get("inputs", {}),
        "algorithms": [
            {
                "taskId": str(task.id),
                "versionId": task.version_id,
                "version": task.version.version,
                "checksum": task.version.checksum,
            }
            for task in tasks
        ],
    }


def _file_bytes(path: Path, *, expected: dict | None = None) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ComputeError("独立评价文件不存在或来源已变化", 409)
    size = path.stat().st_size
    if size > MAX_FILE_BYTES or (expected and size != expected["sizeBytes"]):
        raise ComputeError("独立评价文件大小已变化或超过限制", 409)
    content = path.read_bytes()
    if expected and _hash(content) != expected["checksum"]:
        raise ComputeError("独立评价文件校验失败，内容已变化", 409)
    return content


def _load(workflow) -> dict | None:
    directory = validation_directory(workflow)
    if not directory.exists():
        return None
    if (
        directory.is_symlink()
        or directory.resolve().parent != app_path("workflow-validations").resolve()
    ):
        raise ComputeError("独立评价目录来源已变化", 409)
    try:
        manifest_path, seal_path = (
            directory / "manifest.json",
            directory / "manifest.sha256",
        )
        if (
            manifest_path.is_symlink()
            or seal_path.is_symlink()
            or manifest_path.stat().st_size > MAX_MANIFEST_BYTES
        ):
            raise ComputeError("独立评价清单来源无效", 409)
        content = manifest_path.read_bytes()
        if _hash(content) != seal_path.read_text(encoding="ascii").strip():
            raise ComputeError("独立评价清单校验失败", 409)
        manifest = json.loads(content)
        if (
            set(manifest) != {"schemaVersion", "binding", "summary", "files"}
            or manifest["schemaVersion"] != 1
            or manifest["binding"] != _binding(workflow)
        ):
            raise ComputeError("评价与当前任务、输入或算法版本不一致，请重新核对", 409)
        _summary(manifest["summary"])
        files, seen = manifest["files"], set()
        if not isinstance(files, list):
            raise ComputeError("独立评价文件清单无效", 409)
        for item in files:
            if not isinstance(item, dict) or set(item) != {
                "key",
                "fileName",
                "storedName",
                "contentType",
                "sizeBytes",
                "checksum",
            }:
                raise ComputeError("独立评价文件清单无效", 409)
            key = item["key"]
            if not isinstance(key, str) or not KEY.fullmatch(key) or key in seen:
                raise ComputeError("独立评价文件键无效", 409)
            seen.add(key)
            suffix = Path(item["storedName"]).suffix
            if (
                suffix not in TYPES
                or item["storedName"] != key + suffix
                or item["contentType"] != TYPES[suffix]
            ):
                raise ComputeError("独立评价文件类型或来源无效", 409)
            if (
                Path(item["fileName"]).name != item["fileName"]
                or "/" in item["fileName"]
                or "\\" in item["fileName"]
            ):
                raise ComputeError("独立评价下载名称无效", 409)
            _file_bytes(directory / item["storedName"], expected=item)
        return manifest
    except (
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    ) as exc:
        raise ComputeError("独立评价清单或文件不可用，请核对已保存版本", 409) from exc


def publish_validation(workflow, summary: dict, files: dict[str, Path]) -> dict:
    """Explicit operator import. Evaluation never enters plan/evidence/tool inputs."""
    if workflow.status != "succeeded":
        raise ComputeError("请在科研任务完成后登记独立评价", 409)
    normalized = _summary(summary)
    contents, entries = {}, []
    if not isinstance(files, dict) or len(files) > 30:
        raise ComputeError("评价文件清单无效", 400)
    for key, source in sorted(files.items()):
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise ComputeError("评价文件键无效", 400)
        source = Path(source)
        suffix = source.suffix.lower()
        if suffix not in TYPES:
            raise ComputeError("评价文件仅支持 Markdown、CSV、JSON 和 TXT", 400)
        content = _file_bytes(source)
        try:
            text = content.decode("utf-8-sig")
        except UnicodeError as exc:
            raise ComputeError("评价文件必须使用 UTF-8 编码", 400) from exc
        if PRIVATE_PATH.search(text):
            raise ComputeError("评价文件含内部来源路径，请先移除私有路径", 400)
        filename = _text(source.name, 180)
        contents[key + suffix] = content
        entries.append(
            {
                "key": key,
                "fileName": filename,
                "storedName": key + suffix,
                "contentType": TYPES[suffix],
                "sizeBytes": len(content),
                "checksum": _hash(content),
            }
        )
    manifest = {
        "schemaVersion": 1,
        "binding": _binding(workflow),
        "summary": normalized,
        "files": entries,
    }
    content = _bytes(manifest)
    if len(content) > MAX_MANIFEST_BYTES:
        raise ComputeError("评价清单过大，请将明细保存为文件", 400)
    existing = _load(workflow)
    if existing is not None:
        if existing != manifest:
            raise ComputeError("该任务已绑定不同的独立评价，保留原版本并拒绝覆盖", 409)
        return existing
    directory = validation_directory(workflow)
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".validation-", dir=directory.parent
    ) as temporary:
        staging = Path(temporary)
        for name, payload in contents.items():
            (staging / name).write_bytes(payload)
        (staging / "manifest.json").write_bytes(content)
        (staging / "manifest.sha256").write_text(_hash(content), encoding="ascii")
        try:
            os.rename(staging, directory)
        except OSError as exc:
            if _load(workflow) != manifest:
                raise ComputeError("评价已被其他操作登记，请核对已有版本", 409) from exc
    return manifest


def validation_json(workflow, user) -> dict:
    manifest = _load(workflow)
    base = {"workflowId": str(workflow.id), "available": manifest is not None}
    if manifest is None:
        return {
            **base,
            "scope": "本次科研任务",
            "summary": "本次任务尚未登记独立评价。",
            "sections": [],
            "files": [],
        }
    url = f"/api/agent/workflows/{workflow.id}/validation/files/"
    return {
        **base,
        **manifest["summary"],
        "files": [
            {
                key: item[key]
                for key in ("key", "fileName", "contentType", "sizeBytes", "checksum")
            }
            | {
                "previewUrl": url + item["key"] + "/preview/"
                if item["contentType"] == "text/markdown"
                else None,
                "downloadUrl": url + item["key"] + "/download/",
                "canDownload": permission(user, "catalog.export_dataresource"),
            }
            for item in manifest["files"]
        ],
    }


def load_validation_file(workflow, file_key: str) -> tuple[dict, bytes]:
    if not KEY.fullmatch(file_key):
        raise ComputeError("评价文件不存在", 404)
    manifest = _load(workflow)
    item = (
        next((item for item in manifest["files"] if item["key"] == file_key), None)
        if manifest
        else None
    )
    if item is None:
        raise ComputeError("评价文件不存在", 404)
    return item, _file_bytes(
        validation_directory(workflow) / item["storedName"], expected=item
    )
