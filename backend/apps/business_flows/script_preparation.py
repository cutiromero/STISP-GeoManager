"""Generate, optionally review and repair code inside a fixed business flow."""

from copy import deepcopy
import hashlib
import json
import time

from django.core.exceptions import PermissionDenied

from apps.agent.policy import fresh_user, require_access
from apps.agent.provider import ModelError
from apps.agent.resource_discovery import acl_resources
from apps.agent.workflow_resources import resolve_workflow_resource
from apps.compute.models import AlgorithmVersion
from apps.compute.packages import ComputeError
from apps.compute.services import allowed_algorithms, agent_algorithm_allowed
from .state import binding, emit
from .model_requests import admit
from .script_bridges import choose_bridge, input_bindings, planned_script, versions

PUBLIC_ITEM_KEYS = {
    "role",
    "sourceId",
    "sourceName",
    "sourceType",
    "sourceRevision",
    "sourceBands",
    "targetTypes",
    "targetSemantics",
    "status",
    "versionId",
    "checksum",
    "inputKey",
    "outputKey",
    "targetType",
    "taskId",
    "resourceId",
    "outputId",
    "parameters",
    "missingParameters",
    "fieldTargets",
    "nodeId",
    "sourceIds",
    "fields",
    "candidates",
}


def public_item(entry):
    value = {
        key: deepcopy(item) for key, item in entry.items() if key in PUBLIC_ITEM_KEYS
    }
    if entry.get("scriptMode") or entry.get("script"):
        value.pop("parameters", None)
        current = entry.get("scriptCurrent", {})
        codes = entry.get("scriptHistory", [])
        value["script"] = {
            "attempt": entry.get("scriptAttempt", 0),
            "status": entry.get(
                "scriptStatus", entry.get("script", {}).get("status", "planned")
            ),
            "sha256": current.get("sha256", ""),
            "summary": current.get("summary")
            or entry.get("script", {}).get("summary", "正在准备资料衔接"),
            "available": bool(current.get("code") or codes),
            **(
                {"question": entry["scriptQuestion"]}
                if entry.get("scriptQuestion")
                else {}
            ),
            **(
                {"lastError": entry["scriptError"][:600]}
                if entry.get("scriptError")
                else {}
            ),
        }
    return value


def policy(workflow):
    value = workflow.plan.get("inputPreparationPolicy", {})
    if not value.get("allowScripts") or not workflow.parameters.get("_businessFlow"):
        raise ComputeError("本次流程未启用自主衔接脚本")
    return value


def sources(workflow, user, current_policy, entry):
    rows = entry.get("sources") or [
        {"id": entry["sourceId"], "revision": entry["sourceRevision"]}
    ]
    result = []
    protected = {
        workflow.plan.get(key)
        for key in (
            "rulesResourceId",
            "frozen_rules",
            "approved_changes",
            "model_changes",
        )
    }
    for row in rows:
        resource = resolve_workflow_resource(user, current_policy, row["id"], workflow)
        if resource.updated_at.isoformat() != row["revision"]:
            raise PermissionDenied("衔接来源版本已变化，请重新核对资料")
        if resource.pk in protected or resource.source.startswith(
            ("geology-multi-approved:", "geology-multi-frozen-rules:", "demo-changes:")
        ):
            raise PermissionDenied(
                "规则和批准凭据须沿用流程既有协议，不能由适配脚本改写"
            )
        result.append(resource)
    return result


def target_contract(workflow, entry):
    if entry.get("targetContract"):
        return deepcopy(entry["targetContract"])
    from .input_adapters import logical_role

    requirements = {
        item["key"]: item
        for item in binding(workflow)["definitionSnapshot"]["inputRequirements"]
    }
    spec = requirements[logical_role(entry["role"], requirements)]
    return {
        key: deepcopy(spec[key])
        for key in ("dataTypes", "requiredFields", "semanticType", "description")
        if key in spec
    }


def _node(workflow, entry):
    nodes = binding(workflow)["definitionSnapshot"]["nodes"]
    return next(
        item for item in nodes if item["id"] == entry.get("nodeId", nodes[0]["id"])
    )


def save(workflow, entry, message, *, actor="executor", kind="preparing_inputs"):
    node = _node(workflow, entry)
    workflow.current_step = node["id"]
    workflow.detail = message
    emit(workflow, actor, node["id"], kind, message)


def _live_bridge(workflow, entry):
    row = (
        AlgorithmVersion.objects.select_related("algorithm")
        .filter(
            pk=entry["versionId"],
            checksum=entry["checksum"],
            status="published",
            algorithm__enabled=True,
            algorithm__in=allowed_algorithms(),
        )
        .first()
    )
    permitted = policy(workflow).get("algorithmVersionIds")
    if (
        not row
        or not agent_algorithm_allowed(row)
        or (permitted is not None and row.pk not in permitted)
    ):
        raise PermissionDenied("本次受限解释器已停用、换版或超出所选工具范围")
    return row


def _guard(workflow, entry, resources):
    from .engine import live_guard

    base = live_guard(workflow)
    expected = {row.pk: row.updated_at.isoformat() for row in resources}

    def check():
        base()
        user = fresh_user(workflow.owner_id)
        current = require_access(user, "agent", workflow.model)
        if not current.get("operatorEnabled", False):
            raise PermissionDenied("当前策略已关闭资料衔接计算")
        visible = (
            acl_resources(user, current, expected).only("id", "updated_at").in_bulk()
        )
        if set(visible) != set(expected) or any(
            visible[key].updated_at.isoformat() != value
            for key, value in expected.items()
        ):
            raise PermissionDenied("资料衔接来源已变化或撤权")
        _live_bridge(workflow, entry)

    return check


def callbacks(workflow, entry, actor):
    touched = [0.0]

    def record(value):
        if value["status"] == "requesting":
            admit(workflow, value["requestId"])
        audits = entry.setdefault("scriptAudits", [])
        previous = next(
            (item for item in audits if item["requestId"] == value["requestId"]), None
        )
        if previous is None:
            audits.append(deepcopy(value))
        else:
            previous.update(deepcopy(value))
        entry["scriptActivity"] = deepcopy(value)
        if value["status"] in {
            "requesting",
            "failed",
            "completed",
            "accepted",
            "changes_requested",
        }:
            save(
                workflow,
                entry,
                "智能体正在编写资料衔接脚本"
                if actor == "executor"
                else "独立审核智能体正在核对衔接脚本",
                actor=actor,
                kind="script_" + value["status"],
            )

    def progress(value):
        if time.monotonic() - touched[0] >= 0.8:
            entry["scriptProgress"] = deepcopy(value)
            from .state import persist

            persist(workflow)
            touched[0] = time.monotonic()

    return {"on_record": record, "on_progress": progress}


def fallback(workflow, user, current_policy, entry, error):
    settings = policy(workflow)
    resources = sources(workflow, user, current_policy, entry)
    if entry.get("scriptMode"):
        current = entry.get("scriptCurrent", {})
        if current.get("code"):
            current.update(
                status="failed", error=str(error)[:1200], taskId=entry.get("taskId")
            )
            entry.setdefault("scriptHistory", []).append(deepcopy(current))
        if entry.get("scriptAttempt", 0) >= settings[
            "maxRepairs"
        ] + 1 or "IsolationUnavailable" in str(error):
            entry.update(
                status="failed", scriptStatus="failed", scriptError=str(error)[:1200]
            )
            raise ComputeError(
                "资料衔接脚本未能满足输入规范，已保留原始资料和实际诊断："
                + str(error)[:500]
            )
    else:
        bridge = choose_bridge(
            user,
            [row.data_type for row in resources],
            entry["targetTypes"],
            available=versions(permitted=settings.get("algorithmVersionIds")),
        )
        if bridge is None:
            raise ComputeError(str(error))
        planned = planned_script(bridge)
        if planned["status"] != "needs_script":
            raise ComputeError(planned["script"]["summary"])
        entry["previousAdapter"] = {
            key: deepcopy(entry.get(key))
            for key in ("versionId", "checksum", "parameters", "taskId")
        }
        entry.update(planned)
    for key in (
        "taskId",
        "resourceId",
        "outputId",
        "actualParameters",
        "parameters",
        "inputKey",
        "outputKey",
    ):
        entry.pop(key, None)
    entry.update(
        status="needs_script",
        scriptMode=True,
        scriptStatus="repairing",
        scriptError=str(error)[:1200],
    )
    workflow.status = "queued"
    workflow.plan.pop("inputAdaptationComplete", None)
    save(workflow, entry, "智能体将依据实际错误调整资料衔接脚本", kind="script_repair")


def prepare(workflow, user, current_policy, entry):
    from apps.agent import input_script_model
    from .script_evidence import evidence

    settings = policy(workflow)
    if entry["status"] == "needs_clarification":
        return False
    bridge = _live_bridge(workflow, entry)
    resources = sources(workflow, user, current_policy, entry)
    bindings = input_bindings(bridge, resources)
    target = target_contract(workflow, entry)
    cap = bridge.manifest["inputScriptBridge"]
    namespace = {
        "inputPorts": {
            key: next(row.data_type for row in resources if row.pk == identity)
            for key, identity in bindings.items()
        },
        "outputPorts": {
            kind: {
                "key": key,
                "file": next(
                    item["file"]
                    for item in bridge.manifest["outputs"]
                    if item["key"] == key
                ),
            }
            for kind, key in cap["outputPorts"].items()
        },
    }
    guard = _guard(workflow, entry, resources)
    node = _node(workflow, entry)
    guard()
    signature = hashlib.sha256(
        json.dumps(
            {
                "sources": [
                    (item.pk, item.updated_at.isoformat()) for item in resources
                ],
                "target": target,
                "bridge": bridge.checksum,
                "instruction": node.get("instruction", ""),
                "previousParameters": entry.get("previousAdapter", {}).get(
                    "parameters"
                ),
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    entry["scriptInputSignature"] = signature
    peer = next(
        (
            item
            for item in workflow.plan.get("inputAdaptations", [])
            if item is not entry
            and item.get("scriptInputSignature") == signature
            and item.get("resourceId")
            and item["status"] == "ready"
        ),
        None,
    )
    if peer:
        for key in (
            "taskId",
            "resourceId",
            "outputId",
            "scriptCurrent",
            "scriptHistory",
            "parameters",
            "outputKey",
            "targetType",
            "scriptAttempt",
        ):
            if key in peer:
                entry[key] = deepcopy(peer[key])
        entry.update(scriptMode=True, status="ready", scriptStatus="completed")
        return True
    if entry.get("scriptStatus") == "ready" and entry.get("parameters"):
        current = entry.get("scriptCurrent", {})
        if current.get("code") != entry["parameters"].get(cap["codeParameter"]):
            raise PermissionDenied("已准备的脚本内容与实际计算参数不一致")
        return True
    previous = entry.pop("scriptCurrent", {})
    entry["scriptAttempt"] = entry.get("scriptAttempt", 0) + 1
    attempt = entry["scriptAttempt"]
    if attempt > settings["maxRepairs"] + 1:
        raise ComputeError("资料衔接脚本已达到本次返修上限")
    entry.update(status="generating_script", scriptMode=True, scriptStatus="generating")
    workflow.status = "running"
    factual = evidence(workflow, resources, bindings)
    save(workflow, entry, "智能体正在按实际资料编写衔接脚本", kind="script_generating")
    feedback = {
        "error": entry.get("scriptError", ""),
        "previousCode": previous.get("code", ""),
        "userClarification": entry.get("scriptFeedback", ""),
        "previousAdapter": entry.get("previousAdapter", {}),
    }
    try:
        drafted = input_script_model.generate(
            workflow,
            node,
            attempt,
            factual,
            target=target,
            ports=namespace,
            guard=guard,
            callbacks=callbacks(workflow, entry, "executor"),
            policy=current_policy,
            feedback=feedback,
            code_limit=next(
                item.get("maxLength", 2000)
                for item in bridge.manifest["parameters"]
                if item["key"] == cap["codeParameter"]
            ),
        )
        guard()
        if drafted["decision"] == "needs_clarification":
            entry.update(
                status="needs_clarification",
                scriptStatus="needs_clarification",
                scriptQuestion=drafted["question"],
            )
            entry["scriptAttempt"] -= 1
            workflow.status = "waiting_approval"
            save(
                workflow,
                entry,
                drafted["question"],
                kind="input_clarification_required",
            )
            return False
        current = {
            "attempt": attempt,
            "code": drafted["code"],
            "sha256": hashlib.sha256(drafted["code"].encode()).hexdigest(),
            "summary": drafted["summary"],
            "targetType": drafted["targetType"],
            "status": "generated",
            "audit": drafted["audit"],
        }
        entry["scriptCurrent"] = current
        if settings.get("reviewScripts"):
            entry.update(status="reviewing_script", scriptStatus="reviewing")
            save(
                workflow,
                entry,
                "独立审核智能体正在核对衔接脚本",
                actor="reviewer",
                kind="script_reviewing",
            )
            reviewed = input_script_model.review(
                workflow,
                node,
                attempt,
                factual,
                drafted,
                target=target,
                guard=guard,
                callbacks=callbacks(workflow, entry, "reviewer"),
                maximum_repairs=settings["maxRepairs"],
                model_alias=binding(workflow).get("reviewerModel"),
                policy=current_policy,
            )
            guard()
            current["review"] = reviewed
            if reviewed["decision"] != "accept":
                raise ComputeError(
                    reviewed["reason"] + "；" + reviewed["repairInstructions"]
                )
        contract = {**target, "dataTypes": [drafted["targetType"]]}
        contract_limit = next(
            item.get("maxLength", 2000)
            for item in bridge.manifest["parameters"]
            if item["key"] == cap["contractParameter"]
        )
        if len(json.dumps(contract, ensure_ascii=False)) > contract_limit:
            raise ComputeError("目标规范超过受限解释器参数上限")
        entry.update(
            status="convert",
            scriptStatus="ready",
            scriptInputs=bindings,
            targetType=drafted["targetType"],
            outputKey=cap["outputPorts"][drafted["targetType"]],
            parameters={
                cap["codeParameter"]: drafted["code"],
                cap["targetParameter"]: drafted["targetType"],
                cap["contractParameter"]: json.dumps(contract, ensure_ascii=False),
            },
            missingParameters=[],
            fieldTargets={},
        )
        current["status"] = "ready"
        entry.pop("scriptQuestion", None)
        save(
            workflow,
            entry,
            "衔接脚本已生成，将在独立受限进程中运行",
            kind="script_generated",
        )
        return True
    except (ComputeError, ModelError) as error:
        guard()
        fallback(workflow, user, current_policy, entry, error)
        return False
