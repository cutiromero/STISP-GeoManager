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
from .geology_reference import REFERENCE_SOURCE_PREFIX
from .models import AgentRuntime
from .policy import allowed, visible_models, worker_online
from .tools import resources

SOURCE_NOTE = (
    "明确标注的模拟资料；参数来自样例说明及已发布算法，结论由实际计算和模型判断产生。"
)
REAL_SOURCE_NOTE = (
    "师弟提供的真实地质图件局部副本；少量时代录入错误明确标注，依据辞书条件检查和受约束修改。"
    "构造与蚀变提供空间背景，人工精修仅作独立对照。"
    "formation、region、geologic_age为依据辞书补录的演示条件属性，并非师弟原图实测字段；"
    "地区细分未经野外核实，本轮恢复演示字段一致性。"
    "本轮独立验证八宝山组3项；闹仓坚沟组辞书地区为青海玛多县一带，当前当地适用尚未核实。"
)
REVIEW_SOURCE_NOTE = (
    "演示案例：小范围地质图，结合专家知识检查完整覆盖与地层属性，修改前由用户批准。"
)
ROLE_LABELS = {
    "early_image": "前期影像",
    "late_image": "后期影像",
    "valid_mask": "两期共同有效掩膜",
    "zones": "调查分区",
    "context": "背景与观测记录",
    "initial_map": "待检查地质图",
    "coverage": "制图覆盖范围与例外",
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
AGE_MARKERS = {
    "initial_map": ("code", "real-geology-age-initial"),
    "surveys": ("code", "real-geology-age-context"),
    "rules": ("code", "real-geology-age-rules"),
}
REVIEW_MARKERS = {
    "initial_map": ("code", "geology-review-initial"),
    "coverage": ("code", "geology-review-coverage"),
    "rules": ("code", "geology-review-rules"),
}
TITLES = {
    "geology_map_review": "地质成果智能检查与修正",
    "geology_age_correction": "真实地质图件 · 地层时代一致性纠偏",
    "ecology_investigation": "干旱区生态风险评估分析决策",
    "geology_correction": "地质逻辑推理与填图纠偏",
}
PROMPTS = {
    "geology_map_review": (
        "请检查这个项目的待检查地质图，使用演示案例的制图覆盖资料和样例参数。"
        "先检索专家知识，再核对地图的完整覆盖和地层时代属性，说明发现的问题、依据及建议修改。"
        "把建议位置和修改范围展示给我，等我选中并批准后再调用算法修正。"
        "修正完成后读取真实结果重新检查，在地理工作台展示前后变化，生成简短检查报告和统计。"
        "依据不足的地方保留并告诉我需要什么资料。"
    ),
    "geology_age_correction": (
        "请检查师弟提供的真实地质图件局部副本，检索八宝山组等地层辞书知识，"
        "结合地区条件、真实构造与蚀变空间背景，检查明确标注的时代属性录入错误。"
        "自动调用允许的检查和时代编辑算法，只修正规则明确支持的时代字段，"
        "保留类别、岩性和边界，再复核，保存报告并在地理工作台对照修改位置。"
        "人工精修图不作为算法或模型输入；必要问题在对话中问我。"
        "地层标识、地区、时代为辞书补录的演示条件属性，地区细分未经野外核实；"
        "本轮验证预置时代字段一致性，不将其解释为真实定年纠正。"
    ),
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


def _candidate(resource, role: str, scenario: str) -> dict:
    age = scenario == "geology_age_correction"
    review = scenario == "geology_map_review"
    marker_field, marker = (
        REVIEW_MARKERS if review else AGE_MARKERS if age else MARKERS
    )[role]
    simulated = getattr(resource, marker_field) == marker or (
        role == "context" and resource.code == "demo-ecology-context-updated"
    )
    return {
        "id": resource.id,
        "name": resource.name,
        "dataType": resource.data_type,
        "revision": resource.updated_at.isoformat(),
        "description": resource.description[:800],
        "sourceNote": (
            REVIEW_SOURCE_NOTE if review else REAL_SOURCE_NOTE if age else SOURCE_NOTE
        )
        if simulated
        else resource.source[:160],
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
        age = scenario == "geology_age_correction"
        review = scenario == "geology_map_review"
        markers = REVIEW_MARKERS if review else AGE_MARKERS if age else MARKERS
        inputs, preferred = {}, {}
        for role, kind in roles.items():
            field, marker = markers[role]
            candidates = query.filter(data_type=kind)
            if age or review:
                candidates = candidates.exclude(
                    source__startswith=REFERENCE_SOURCE_PREFIX
                )
            if review:
                candidates = candidates.exclude(
                    source__startswith="geology-review-reference:"
                ).exclude(source__startswith="geology-review-acceptance:")
            if not manual:
                from django.db.models import Q

                condition = Q(**{field: marker})
                if role == "context":
                    condition |= Q(code="demo-ecology-context-updated")
                candidates = candidates.filter(condition)
            rows = list(candidates.order_by("id")[:25])
            inputs[role] = [_candidate(resource, role, scenario) for resource in rows]
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
                "roleLabels": {
                    role: "空间背景与资料说明"
                    if age and role == "surveys"
                    else ROLE_LABELS[role]
                    for role in roles
                },
                "inputs": inputs,
                "preferredInputs": preferred,
                "defaults": defaults,
                "parameterSpecs": specs,
                "algorithms": algorithms,
                "available": all(inputs.values())
                and len(algorithms) == len(identifiers),
                "sourceNote": REVIEW_SOURCE_NOTE
                if review
                else REAL_SOURCE_NOTE
                if age
                else SOURCE_NOTE,
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
                # Historical workflows remain readable and manually selectable.
                if scene["scenario"] in {
                    "geology_correction",
                    "geology_age_correction",
                }:
                    continue
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
                        "sampleNature": (
                            "demonstration_case"
                            if scene["scenario"] == "geology_map_review"
                            else "synthetic"
                        ),
                        "available": bool(
                            shared_ready
                            and scene["available"]
                            and len(scene["inputs"]) <= p["maxResources"]
                            and len(GRAPHS[scene["scenario"]]) <= p["maxOperatorSteps"]
                            and len(GRAPHS[scene["scenario"]])
                            + (2 if scene["scenario"] == "geology_map_review" else 1)
                            <= p["maxIterations"]
                        ),
                    }
                )
    return {"items": items}
