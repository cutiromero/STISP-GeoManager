"""Generic geology workflow over user uploads.

The user binds uploaded files to roles; the model proposes what each field
means; after the user confirms, normalized working copies feed the existing
multi-element operators, decisions and approvals unchanged.
"""

from __future__ import annotations

import math

from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.compute.packages import ComputeError

from .geology_multi import SCENARIO as MULTI_TYPE
from .tools import resolve_resource, resources

GENERIC = "geology_generic"
MULTI_FAMILY = {MULTI_TYPE, GENERIC}
MINERALS = ("hematite", "chlorite", "hydromica", "calcite", "dolomite")
ROLES = {
    "lithology": "vector",
    "faults": "vector",
    "coverage": "vector",
    "units": "table",
    **{mineral: "raster" for mineral in MINERALS},
}
GEOMETRY = {"lithology": "Polygon", "faults": "LineString", "coverage": "Polygon"}
LABELS = {
    "lithology": "地质图",
    "faults": "构造线",
    "coverage": "研究区范围",
    "units": "填图单元表",
    "hematite": "赤铁矿化识别结果",
    "chlorite": "绿泥石化识别结果",
    "hydromica": "水云母化识别结果",
    "calcite": "方解石化识别结果",
    "dolomite": "白云石化识别结果",
}
# (key, label, required, name keywords). Object IDs are never mapped: working
# copies get neutral generated IDs so labels in a user's IDs cannot reach checks.
TARGETS = {
    "lithology": (
        (
            "name",
            "地层或填图单元名称",
            True,
            ("name", "dcmc", "地层", "单元", "岩性", "formation", "unit", "名称", "mc"),
        ),
        ("geo_sym", "代号", False, ("geo_sym", "sym", "code", "代号", "dh", "symbol")),
        (
            "conf",
            "分类置信度（0～1）",
            False,
            ("conf", "confidence", "置信", "prob", "score"),
        ),
    ),
    "coverage": (
        ("role", "范围或例外（exclusion 表示例外区）", False, ("role", "类型", "type")),
    ),
    "units": (
        ("code", "代号", True, ("code", "geo_sym", "sym", "代号", "dh")),
        ("name", "名称", False, ("name", "名称", "单元", "地层", "mc")),
        (
            "category",
            "类别（cover/stratum/intrusive）",
            False,
            ("category", "类别", "lb"),
        ),
        ("age_ma", "近似年龄（Ma）", False, ("age_ma", "age", "年龄", "ma")),
        ("group", "岩石组", False, ("group", "岩石", "组别")),
        ("favorable", "是否有利赋矿岩性", False, ("favorable", "有利")),
    ),
}
PARAMETERS = {"grid_resolution_m": (10, 1000), "min_zone_area_m2": (0, 100_000_000)}


def project_rules(user, policy):
    rules = (
        resources(user, policy)
        .filter(
            status="active", data_type="table", code__startswith="geology-multi-rules"
        )
        .order_by("-updated_at", "-id")
        .first()
    )
    if rules is None:
        raise ComputeError("当前项目没有已绑定的地质试用规则，请联系管理员登记")
    return rules


def generic_ready(user, policy):
    """None when the project has no bound rules; else whether operators are published."""
    from apps.compute.models import AlgorithmVersion
    from apps.compute.services import agent_algorithm_allowed, allowed_algorithms

    from .geology_multi import graph

    try:
        project_rules(user, policy)
    except ComputeError:
        return None
    needed = {identifier for _, identifier, _ in graph()}
    published = {
        version.algorithm.identifier
        for version in AlgorithmVersion.objects.select_related("algorithm").filter(
            status="published",
            algorithm__enabled=True,
            algorithm__in=allowed_algorithms(),
            algorithm__identifier__in=needed,
        )
        if agent_algorithm_allowed(version)
    }
    return published == needed


def _uploads(user, inputs, batch_id):
    from .models import WorkflowUpload

    query = WorkflowUpload.objects.select_related("resource").filter(
        owner=user, resource_id__in=list(inputs.values()), batch_id=batch_id
    )
    return {upload.resource_id: upload for upload in query}


def validate_creation(user, policy, inputs, parameters, batch_id, key):
    """Check roles against the batch's real files; return the project rules id.

    A batch already bound to the workflow with this idempotency key passes so a
    retried request returns that workflow instead of a conflict.
    """
    from .models import AgentWorkflow
    from .workflow_uploads import batch_uploads

    if (
        not isinstance(inputs, dict)
        or "lithology" not in inputs
        or set(inputs) - set(ROLES)
    ):
        raise ComputeError("请至少指定地质图，其他资料角色可选")
    if len(set(inputs.values())) != len(inputs):
        raise ComputeError("同一份资料只能对应一个角色")
    if set(parameters) - set(PARAMETERS):
        raise ComputeError("通用地质推理只接受网格分辨率和最小远景区面积参数")
    for name, (low, high) in PARAMETERS.items():
        value = parameters.get(name)
        if value is not None and (
            type(value) not in {int, float}
            or not math.isfinite(value)
            or not low <= value <= high
        ):
            raise ComputeError("参数超出有效范围：" + name)
    # The run reads three vector copies, the rasters (one shared all-zero stand-in
    # for missing minerals) and the rules, so check the limit before field review.
    rasters = sum(mineral in inputs for mineral in MINERALS)
    working = 3 + rasters + (rasters < len(MINERALS)) + 1
    if policy["maxResources"] > 0 and working > policy["maxResources"]:
        raise ComputeError("场景输入超过当前资源上限")
    uploads = {u.resource_id: u for u in batch_uploads(user, batch_id)}
    bound = {u.workflow_id for u in uploads.values()} - {None}
    if not uploads or (
        bound
        and AgentWorkflow._base_manager.filter(
            pk__in=bound, owner=user, idempotency_key=key
        ).count()
        != len(bound)
    ):
        raise ComputeError("上传批次不存在或已用于其他任务", 409)
    for role, identity in inputs.items():
        resolve_resource(user, policy, identity)
        upload = uploads.get(identity)
        if upload is None:
            raise ComputeError("资料角色只能选择本次任务上传的资料")
        profile = upload.profile
        if upload.resource.data_type != ROLES[role]:
            raise ComputeError(LABELS[role] + "的资料类型不适用")
        expected = GEOMETRY.get(role)
        if expected and not any(
            expected in value for value in profile.get("geometryTypes", [])
        ):
            raise ComputeError(LABELS[role] + "的几何类型不适用")
        if ROLES[role] != "table" and not profile.get("crs"):
            raise ComputeError(LABELS[role] + "缺少坐标系")
        if ROLES[role] == "raster" and profile.get("bandCount") != 1:
            raise ComputeError(LABELS[role] + "须为单波段栅格")
    return project_rules(user, policy).id


def _keyword_score(field, keywords):
    lowered = field["name"].casefold()
    return max((len(word) for word in keywords if word in lowered), default=0)


def heuristic_targets(role, profile):
    fields, used, result = profile.get("fields", []), set(), []
    for key, label, required, keywords in TARGETS[role]:
        ranked = sorted(
            (f for f in fields if f["name"] not in used),
            key=lambda f: _keyword_score(f, keywords),
            reverse=True,
        )
        best = ranked[0] if ranked and _keyword_score(ranked[0], keywords) else None
        if key == "name" and best is None:
            texts = [f for f in fields if f["type"] == "text" and f["name"] not in used]
            best = max(texts, key=lambda f: f["distinctCount"], default=None)
        if key == "conf" and best is not None and best["type"] == "text":
            best = None
        if best:
            used.add(best["name"])
        result.append(
            {
                "key": key,
                "label": label,
                "required": required,
                "field": best["name"] if best else None,
                "reason": (
                    f"字段名“{best['name']}”与{label}相符，示例取值："
                    + "、".join(best["samples"][:3])
                    if best
                    else "未找到对应字段"
                ),
            }
        )
    return result


def _review_roles(workflow, user):
    inputs = workflow.plan["uploadInputs"]
    uploads = _uploads(user, inputs, workflow.plan["uploadBatchId"])
    roles = []
    for role, identity in inputs.items():
        if role not in TARGETS:
            continue
        upload = uploads[identity]
        roles.append(
            {
                "role": role,
                "label": LABELS[role],
                "resourceId": identity,
                "fileName": upload.file_name,
                "fields": [f["name"] for f in upload.profile.get("fields", [])],
                "targets": heuristic_targets(role, upload.profile),
                "_profile": upload.profile,
            }
        )
    return roles


def _questions(roles):
    return [
        f"{item['label']}中没有找到“{target['label']}”，请指定对应字段"
        for item in roles
        for target in item["targets"]
        if target["required"] and not target["field"]
    ]


def propose_mapping(workflow, user, policy):
    from .generic_mapping import model_targets

    roles = _review_roles(workflow, user)
    mode, note = "mock", []
    try:
        proposed = model_targets(workflow, policy, roles)
    except ComputeError as exc:
        proposed, note = (
            None,
            [
                "智能体未能完成字段判断（"
                + str(exc)[:80]
                + "），以下为平台按字段名给出的建议，请逐项核对"
            ],
        )
    if proposed is not None:
        mode = "real"
        for item in roles:
            for target in item["targets"]:
                value = proposed.get(item["role"], {}).get(target["key"])
                if value:
                    target["field"], target["reason"] = value["field"], value["reason"]
    for item in roles:
        item.pop("_profile")
    return {
        "roles": roles,
        "questions": note + _questions(roles),
        "modelMode": mode,
        "confirmed": False,
    }


def validate_mapping(review, mapping):
    if not isinstance(mapping, dict) or set(mapping) != {
        item["role"] for item in review["roles"]
    }:
        raise ComputeError("请为每份需要确认的资料提交字段对应")
    confirmed = {}
    for item in review["roles"]:
        value = mapping[item["role"]]
        keys = {target["key"] for target in item["targets"]}
        if not isinstance(value, dict) or set(value) - keys:
            raise ComputeError(item["label"] + "的字段对应无效")
        chosen = {}
        for target in item["targets"]:
            field = value.get(target["key"])
            if field is not None and (
                not isinstance(field, str) or field not in item["fields"]
            ):
                raise ComputeError(f"{item['label']}没有字段“{field}”")
            if target["required"] and not field:
                raise ComputeError(f"请指定{item['label']}的“{target['label']}”")
            chosen[target["key"]] = field
        picked = [field for field in chosen.values() if field]
        if len(picked) != len(set(picked)):
            raise ComputeError(item["label"] + "中同一字段不能对应多个含义")
        confirmed[item["role"]] = chosen
    return confirmed


def confirm_mapping(workflow, user, policy, plan_hash, mapping):
    from .demo_workflow import _save
    from .workflow import _state_hash, step

    if workflow.status != "waiting_approval" or workflow.cancel_requested:
        raise ComputeError("当前不能确认字段", 409)
    if plan_hash != workflow.plan_hash or _state_hash(workflow.plan) != plan_hash:
        raise ComputeError("字段建议已变化，请刷新后确认", 409)
    for identity in workflow.resource_ids:
        resolve_resource(user, policy, identity)
    review = workflow.plan["fieldMappingReview"]
    confirmed = validate_mapping(review, mapping)
    review["confirmed"] = True
    workflow.plan.update(confirmedMapping=confirmed, phase="build_inputs")
    workflow.status, workflow.detail = "queued", "已确认字段含义，正在生成工作副本"
    with transaction.atomic():
        _save(workflow)
        from .logic_configuration import save_configuration

        save_configuration(workflow, confirmed)
        step(
            workflow,
            "field_mapping_confirmed",
            action=confirmed,
            message="用户已确认字段含义",
        )


def utm_epsg(bounds):
    lon, lat = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
    zone = min(60, int((lon + 180) // 6) + 1)
    return (32600 if lat >= 0 else 32700) + zone


def prepare_generic(workflow, user, policy) -> bool:
    """Return True while the workflow waits for the user's field confirmation."""
    from .demo_workflow import _save
    from .workflow import checkpoint, step

    phase = workflow.plan.get("phase")
    if phase is None:
        reused = workflow.plan.pop("reusedFieldMapping", None)
        if reused is not None:
            from .logic_configuration import matching_configuration
            from .models import AgentRun
            from .workflow_uploads import batch_uploads

            origin = (
                AgentRun.objects.filter(research_workflow=workflow, owner=user)
                .order_by("id")
                .first()
            )
            uploads = list(batch_uploads(user, workflow.plan["uploadBatchId"]))
            if origin and matching_configuration(origin, uploads):
                roles = _review_roles(workflow, user)
                for item in roles:
                    item.pop("_profile")
                review = {
                    "roles": roles,
                    "questions": [],
                    "modelMode": "mock",
                    "confirmed": False,
                }
                try:
                    confirmed = validate_mapping(review, reused)
                except ComputeError:
                    pass
                else:
                    review["confirmed"] = True
                    workflow.plan.update(
                        fieldMappingReview=review,
                        confirmedMapping=confirmed,
                        phase="build_inputs",
                        reusedConfiguration=True,
                    )
                    _save(workflow)
                    from .logic_configuration import save_configuration

                    save_configuration(workflow, confirmed)
                    return prepare_generic(workflow, user, policy)
        review = propose_mapping(workflow, user, policy)
        workflow.plan.update(fieldMappingReview=review, phase="review_mapping")
        workflow.status, workflow.current_step = "waiting_approval", "review_mapping"
        workflow.detail = "请确认各资料的字段含义"
        with transaction.atomic():
            _save(workflow)
            step(workflow, "field_mapping", action=review, message=workflow.detail)
            checkpoint(workflow, "review_mapping", {"planHash": workflow.plan_hash})
        return True
    if phase == "review_mapping":
        return True
    if phase in {"build_inputs", "inputs_ready"}:
        # Copies are saved before the plan; a restarted worker resumes from here.
        from .generic_inputs import build_inputs

        build_inputs(workflow, user, policy)
        return False
    raise PermissionDenied("通用地质推理任务状态无效")
