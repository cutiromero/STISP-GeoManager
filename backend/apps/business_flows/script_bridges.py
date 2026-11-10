"""Discover confined interpreters by their published capabilities, not IDs."""

from collections import Counter

from apps.compute.models import AlgorithmVersion
from apps.compute.runtime import script_isolation_status
from apps.compute.script_capabilities import RUNTIME
from apps.compute.services import agent_algorithm_allowed, allowed_algorithms


def versions(*, permitted=None, pinned=None):
    rows = (
        AlgorithmVersion.objects.select_related("algorithm")
        .filter(
            algorithm__in=allowed_algorithms(),
            algorithm__enabled=True,
            status="published",
            manifest__runtime=RUNTIME,
            manifest__inputScriptBridge__isnull=False,
        )
        .order_by("-created_at", "-pk")
    )
    if pinned is not None:
        rows = rows.filter(pk=pinned)
    if permitted is not None:
        rows = rows.filter(pk__in=permitted)
    return [
        row
        for row in rows
        if isinstance(row.manifest.get("inputScriptBridge"), dict)
        and agent_algorithm_allowed(row)
    ]


def choose_bridge(user, source_types, target_types, *, available=None):
    counts = Counter(source_types)
    for version in versions() if available is None else available:
        cap = version.manifest.get("inputScriptBridge")
        if not isinstance(cap, dict):
            continue
        if set(target_types) & set(cap["outputPorts"]) and all(
            count <= len(cap["inputPorts"].get(kind, []))
            for kind, count in counts.items()
        ):
            return version
    return None


def planned_script(version):
    capability = script_isolation_status()
    available = bool(capability.get("available"))
    return {
        "status": "needs_script" if available else "unavailable",
        "versionId": version.pk,
        "checksum": version.checksum,
        "script": {
            "attempt": 0,
            "status": "planned" if available else "unavailable",
            "sha256": "",
            "available": False,
            "summary": "由智能体根据实际资料编写衔接脚本，生成符合输入规范的工作副本"
            if available
            else capability.get("reason", "受限脚本环境暂不可用"),
        },
    }


def input_bindings(version, resources):
    cap = version.manifest["inputScriptBridge"]
    counts, result = Counter(), {}
    for resource in resources:
        ports = cap["inputPorts"].get(resource.data_type, [])
        index = counts[resource.data_type]
        if index >= len(ports):
            from apps.compute.packages import ComputeError

            raise ComputeError("本次资料数量超过解释器实际端口范围")
        result[ports[index]] = resource.pk
        counts[resource.data_type] += 1
    return result
