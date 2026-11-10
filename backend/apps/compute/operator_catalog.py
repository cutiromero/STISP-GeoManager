"""面向模型上下文的只读算子目录，沿用计算中心授权与共享范围。"""

from copy import deepcopy
import json

from apps.projects.context import ProjectScope, project_scope
from .access import require_actor
from .models import AlgorithmVersion
from .packages import ComputeError
from .services import agent_algorithm_allowed, allowed_algorithms
from .manifest_v2 import OPERATIONS

DEFAULT_MAX_BYTES = 8192
MAX_CATALOG_ITEMS = 100


def _encoded_size(value):
    return len(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def compact_description(version, max_bytes=DEFAULT_MAX_BYTES):
    manifest = version.manifest
    capability = manifest.get("capabilities")
    if not isinstance(capability, dict):
        capability = {"summary": manifest.get("description", "")}
    value = {
        "versionId": version.pk,
        "identifier": version.algorithm.identifier,
        "version": version.version,
        "schemaVersion": manifest.get("schemaVersion", 1),
        "name": version.algorithm.name,
        "capabilities": deepcopy(capability),
        "inputs": deepcopy(manifest.get("inputs", [])),
        "parameters": [
            deepcopy(item)
            for item in manifest.get("parameters", [])
            if isinstance(item.get("agent"), dict)
            and item["agent"].get("adjustable") is True
        ],
        "outputs": deepcopy(manifest.get("outputs", [])),
        "errors": deepcopy(manifest.get("errors", [])),
        "truncated": False,
    }
    if _encoded_size(value) <= max_bytes:
        return value
    value["truncated"] = True
    value["summaryCounts"] = {
        key: len(value[key]) for key in ("inputs", "parameters", "outputs", "errors")
    }
    for key in ("inputs", "parameters", "outputs", "errors"):
        while value[key] and _encoded_size(value) > max_bytes:
            value[key].pop()
    if _encoded_size(value) > max_bytes:
        capability = value["capabilities"]
        value["capabilities"] = {
            "operations": capability.get("operations", []),
            "dataTypes": capability.get("dataTypes", []),
            "summary": capability.get("summary", "")[:80],
        }
        value["name"] = value["name"][:80]
    if _encoded_size(value) > max_bytes:
        raise ComputeError("算子目录体量上限不足以容纳身份摘要")
    return value


def operator_catalog(
    user,
    project,
    *,
    operation=None,
    data_type=None,
    keyword="",
    max_bytes=DEFAULT_MAX_BYTES,
    limit=50,
):
    """每个算法返回最新可调用发布版本；max_bytes为UTF-8紧凑JSON字节数。"""
    selected = project.pk if hasattr(project, "pk") else project
    require_actor(user, selected, "submit_task", "core.browse_data")
    if operation is not None and operation not in OPERATIONS:
        raise ComputeError("未知操作类别")
    if (
        type(max_bytes) is not int
        or not 1024 <= max_bytes <= 32768
        or type(limit) is not int
        or not 1 <= limit <= MAX_CATALOG_ITEMS
    ):
        raise ComputeError("目录上限须为1024至32768字节，条数须为1至100")
    if not isinstance(keyword, str) or len(keyword) > 160:
        raise ComputeError("关键词须为至多160字文字")
    from .packages import EXTENSIONS

    if data_type is not None and data_type not in EXTENSIONS:
        raise ComputeError("未知数据类型")
    with project_scope(
        ProjectScope(ids=(1, selected), selected=selected, user_id=user.pk)
    ):
        rows = (
            AlgorithmVersion.objects.select_related("algorithm")
            .filter(
                algorithm__in=allowed_algorithms().filter(enabled=True),
                status="published",
            )
            .order_by("algorithm_id", "-created_at", "-id")
        )
        result, seen = [], set()
        for version in rows.iterator(chunk_size=100):
            if version.algorithm_id in seen or not agent_algorithm_allowed(version):
                continue
            seen.add(version.algorithm_id)
            manifest = version.manifest
            capability = manifest.get("capabilities", {})
            if not isinstance(capability, dict):
                capability = {}
            if operation and operation not in capability.get("operations", []):
                continue
            kinds = capability.get(
                "dataTypes", [item["kind"] for item in manifest.get("inputs", [])]
            )
            if data_type and data_type not in kinds:
                continue
            searchable = " ".join(
                (
                    version.algorithm.identifier,
                    version.algorithm.name,
                    manifest.get("description", ""),
                    json.dumps(capability, ensure_ascii=False),
                )
            )
            if keyword and keyword.casefold() not in searchable.casefold():
                continue
            result.append(compact_description(version, max_bytes))
            if len(result) >= limit:
                break
    return result
