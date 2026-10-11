"""Discover authorized Demo inputs; keep scientific answers out of presets."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.compute.models import AlgorithmVersion
from apps.compute.services import (
    agent_algorithm_allowed,
    allowed_algorithms,
    runtime_state,
)
from apps.projects.context import ProjectScope, is_superadmin, project_scope
from apps.projects.middleware import models_q
from apps.projects.models import Project

from .demo_workflow import GRAPHS, ROLES
from .models import AgentRuntime
from .policy import allowed, visible_models, worker_online
from .tools import resources

SOURCE_NOTE = (
    "明确标注的模拟资料；参数来自样例说明及已发布算法，结论由实际计算和模型判断产生。"
)
ROLE_LABELS = {
    "early_image": "前期影像",
    "late_image": "后期影像",
    "valid_mask": "两期共同有效掩膜",
    "zones": "调查分区",
    "context": "背景与观测记录",
    "initial_map": "待检查初始填图",
    "surveys": "调查证据",
    "rules": "允许修改规则",
}
MARKERS = {
    "early_image": ("source", "demo-ecology-early-image"),
    "late_image": ("source", "demo-ecology-late-image"),
    "valid_mask": ("source", "demo-ecology-valid-mask"),
    "zones": ("code", "demo-ecology-zones"),
    "context": ("code", "demo-ecology-context-initial"),
    "initial_map": ("code", "demo-geology-initial"),
    "surveys": ("code", "demo-geology-surveys"),
    "rules": ("code", "demo-geology-rules"),
}
TITLES = {
    "ecology_investigation": "干旱区生态风险评估分析决策",
    "geology_correction": "地质逻辑推理与填图纠偏",
}
PROMPTS = {
    "ecology_investigation": (
        "请使用这个项目中已标注的模拟演示资料和样例参数，分析前后两期植被变化，"
        "结合初始观测与知识库说明变化线索，选出调查优先区和优先补资料区。"
        "自动调用已发布算法完成计算，保存报告和地图成果，说明每一步依据；"
        "确实缺少信息时在对话里问我。完成后我还会补入新观测，请据此更新建议。"
    ),
    "geology_correction": (
        "请使用这个项目中已标注的模拟初始填图、调查记录、小规则集和样例参数，"
        "检查并纠正证据明确支持的问题，再检查修改后的地图。"
        "自动调用已发布算法，保存原图与修改图的对照成果和修改原因报告；"
        "需要我审核的几何候选请在对话里展示具体问题后让我选择。"
    ),
}


def _algorithms(run) -> list[dict]:
    selected = set(run.algorithm_version_ids or []) if run else set()
    query = AlgorithmVersion.objects.select_related("algorithm").filter(
        algorithm__in=allowed_algorithms(),
        algorithm__enabled=True,
        status="published",
    )
    if run and run.algorithm_selection_mode == "manual":
        query = query.filter(pk__in=selected)
    versions = {}
    for version in query.order_by("-created_at", "-id"):
        identifier = version.algorithm.identifier
        if identifier in versions or not agent_algorithm_allowed(version):
            continue
        versions[identifier] = {
            "identifier": identifier,
            "versionId": version.id,
            "name": version.algorithm.name,
            "manifest": version.manifest,
            "checksum": version.checksum,
        }
    return list(versions.values())


def _candidate(resource, role: str) -> dict:
    marker_field, marker = MARKERS[role]
    simulated = getattr(resource, marker_field) == marker or (
        role == "context" and resource.code == "demo-ecology-context-updated"
    )
    return {
        "id": resource.id,
        "name": resource.name,
        "dataType": resource.data_type,
        "revision": resource.updated_at.isoformat(),
        "description": resource.description[:800],
        "sourceNote": SOURCE_NOTE if simulated else resource.source[:160],
        "isUpdate": resource.code == "demo-ecology-context-updated",
        "isPreset": simulated,
    }


def _parameters(algorithms: list[dict], sample_images: bool) -> tuple[list, dict]:
    specs, defaults = {}, {}
    for algorithm in algorithms:
        for spec in algorithm["manifest"].get("parameters", []):
            key = spec["key"]
            specs.setdefault(key, dict(spec))
            if "default" in spec:
                defaults[key] = spec["default"]
    # Band and date presets describe these synthetic rasters only.
    if {"early_date", "late_date"} <= set(specs):
        for key in ("early_date", "late_date"):
            specs[key]["type"] = "date"
        if sample_images:
            defaults.update(
                red=1, nir=2, early_date="2025-09-15", late_date="2026-09-15"
            )
        else:
            for key in ("red", "nir", "early_date", "late_date"):
                defaults.pop(key, None)
                if key in specs:
                    specs[key].pop("default", None)
    return list(specs.values()), defaults


def discover(user, p: dict, run=None) -> dict:
    """Current project only; manual selections are a ceiling, never a suggestion."""
    selected = list(run.resource_ids or []) if run else []
    manual = bool(run and run.data_selection_mode == "manual")
    query = resources(user, p, selected).filter(status="active")
    if manual and not selected:
        query = query.none()
    available_algorithms = _algorithms(run)
    scenarios = []
    for scenario, roles in ROLES.items():
        inputs, preferred = {}, {}
        for role, kind in roles.items():
            field, marker = MARKERS[role]
            candidates = query.filter(data_type=kind)
            if not manual:
                from django.db.models import Q

                condition = Q(**{field: marker})
                if role == "context":
                    condition |= Q(code="demo-ecology-context-updated")
                candidates = candidates.filter(condition)
            rows = list(candidates.order_by("id")[:25])
            inputs[role] = [_candidate(resource, role) for resource in rows]
            matches = [
                resource for resource in rows if getattr(resource, field) == marker
            ]
            if len(matches) == 1:
                preferred[role] = matches[0].id
        identifiers = {identifier for _, identifier, _ in GRAPHS[scenario]}
        algorithms = [a for a in available_algorithms if a["identifier"] in identifiers]
        sample_images = all(role in preferred for role in ("early_image", "late_image"))
        specs, defaults = _parameters(algorithms, sample_images)
        scenarios.append(
            {
                "scenario": scenario,
                "workflowType": scenario,
                "title": TITLES[scenario],
                "roleLabels": {role: ROLE_LABELS[role] for role in roles},
                "inputs": inputs,
                "preferredInputs": preferred,
                "defaults": defaults,
                "parameterSpecs": specs,
                "algorithms": algorithms,
                "available": all(inputs.values())
                and len(algorithms) == len(identifiers),
                "sourceNote": SOURCE_NOTE,
            }
        )
    return {"scenarios": scenarios}


def list_demos(user, p: dict) -> dict:
    """Navigation across authorized projects, without exposing private input names."""
    if not allowed(user, "agent", p):
        return {"items": []}
    projects = Project.objects.filter(is_active=True)
    superadmin = is_superadmin(user)
    if not superadmin:
        projects = projects.filter(models_q(user)).distinct()
    models_ready = any(
        m["status"] == "online" for m in visible_models(user, "agent", p)
    )
    runtime = runtime_state(user)
    workflow_ready = AgentRuntime.objects.filter(
        name="workflow-worker",
        heartbeat__gt=timezone.now() - timedelta(seconds=120),
    ).exists()
    shared_ready = bool(
        p.get("workflowEnabled")
        and p.get("operatorEnabled")
        and worker_online()
        and workflow_ready
        and models_ready
        and runtime["available"]
        and runtime["permissions"]["submit_task"]
        and runtime["permissions"]["view_own_task"]
        and runtime["permissions"]["import_outputs"]
    )
    items = []
    for project in projects.order_by("id"):
        with project_scope(
            ProjectScope((project.id,), project.id, user.id, superadmin)
        ):
            for scene in discover(user, p)["scenarios"]:
                # Only advertise projects with some authorized scenario inputs.
                if not any(scene["inputs"].values()):
                    continue
                items.append(
                    {
                        "scenario": scene["scenario"],
                        "projectId": project.id,
                        "projectName": project.name,
                        "title": scene["title"],
                        "prompt": PROMPTS[scene["scenario"]],
                        "sampleNature": "synthetic",
                        "available": bool(
                            shared_ready
                            and scene["available"]
                            and len(scene["inputs"]) <= p["maxResources"]
                            and len(GRAPHS[scene["scenario"]]) <= p["maxOperatorSteps"]
                            and len(GRAPHS[scene["scenario"]]) + 1 <= p["maxIterations"]
                        ),
                    }
                )
    return {"items": items}
