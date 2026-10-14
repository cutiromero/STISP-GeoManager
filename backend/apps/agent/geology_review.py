"""Evidence-bound suggestions and exact user approval for the map review case."""

from __future__ import annotations

import hashlib
import json
import math

from shapely.geometry import shape
from shapely.errors import GEOSException

from apps.compute.packages import ComputeError
from .demo_results import EDIT_FIELDS, read_results
from .compute_tools import authorized_task

KIND = "geology_map_review"
QUERY_ACTION = "search_expert_knowledge"
EDIT_ACTION = "geology-map-correct"


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def issue_results(workflow):
    stage = next(
        (
            item
            for item in workflow.plan["stages"]
            if item["identifier"] == "geology-map-check" and item.get("taskId")
        ),
        None,
    )
    return [
        item for item in (stage or {}).get("results", []) if item["key"] == "issues"
    ]


def validate_modifications(edits, results):
    if not isinstance(edits, list) or not 1 <= len(edits) <= 30:
        raise ComputeError("请提出至少一项有依据的修改，或保留问题并请求补充资料")
    issues = [
        row
        for item in results
        for row in item.get("rows", [])
        if row.get("status") == "repairable"
        and row.get("kind") in {"fill_gap", "set_age"}
    ]
    accepted, used = [], set()
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {*EDIT_FIELDS, "reason"}:
            raise ComputeError(
                "建议修改仅允许当前问题的对象、原值、新值、依据及简短理由"
            )
        values = {key: str(edit[key]) for key in EDIT_FIELDS}
        if any(
            (not value and key != "old_value") or len(value) > 500
            for key, value in values.items()
        ):
            raise ComputeError("建议修改的对象或依据不完整")
        matches = [
            row
            for row in issues
            if all(str(row.get(key, "")) == values[key] for key in EDIT_FIELDS)
        ]
        if len(matches) != 1:
            raise ComputeError("建议修改不能唯一对应实际检查中的问题")
        row = matches[0]
        if (row["kind"], row["field"]) not in {
            ("fill_gap", "class"),
            ("set_age", "geologic_age"),
        }:
            raise ComputeError("建议修改超出本次允许的操作")
        signature, issue_id = row.get("input_checksum"), row.get("issue_id")
        if (
            not isinstance(signature, str)
            or len(signature) != 64
            or any(ch not in "0123456789abcdef" for ch in signature)
            or not isinstance(issue_id, str)
            or not issue_id
            or issue_id in used
        ):
            raise ComputeError("问题缺少有效内容签名或出现重复建议")
        reason = edit["reason"]
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
            raise ComputeError("每项建议需要简短、明确的依据")
        used.add(issue_id)
        accepted.append(
            {
                **values,
                "reason": reason.strip(),
                "issue_id": issue_id,
                "kind": row["kind"],
                "input_checksum": signature,
            }
        )
    return accepted


def _knowledge(workflow, row, decision):
    from apps.knowledge.services import visible_entries
    from .demo_workflow import _domains

    cited = {
        str(ref["id"])
        for ref in decision.get("evidenceRefs", [])
        if ref.get("kind") == "knowledge"
    }
    if not row.get("knowledge_seed"):
        raise ComputeError("当前检查规则缺少可核对的专家知识定位")
    current = {
        str(entry.id): entry.revision
        for entry in visible_entries(workflow.owner, domains=_domains(workflow)).filter(
            seed_key=row.get("knowledge_seed", "")
        )
    }
    matches = [
        entry
        for entry in workflow.evidence
        if str(entry["id"]) in cited
        and current.get(str(entry["id"])) == entry["revision"]
    ]
    if not matches:
        raise ComputeError("当前建议尚未引用对应规则的实际专家知识，请重新核对知识依据")
    return [
        {"id": entry["id"], "revision": entry["revision"], "title": entry["title"]}
        for entry in matches
    ]


def proposal(workflow, stage, results):
    rows = validate_modifications(stage["edits"], results)
    lookup = {
        row.get("issue_id"): row for item in results for row in item.get("rows", [])
    }
    suggestions = []
    for edit in rows:
        row = lookup[edit["issue_id"]]
        try:
            geometry = json.loads(row["geometry_json"])
            if not isinstance(geometry, dict) or geometry.get("type") not in {
                "Polygon",
                "MultiPolygon",
            }:
                raise ValueError("invalid modification geometry")
            geom = shape(geometry)
            bounds = list(geom.bounds)
            area = float(row["area_m2"])
            valid = (
                geom.geom_type in {"Polygon", "MultiPolygon"}
                and geom.is_valid
                and not geom.is_empty
                and len(bounds) == 4
                and all(math.isfinite(value) for value in bounds)
                and -180 <= bounds[0] <= bounds[2] <= 180
                and -90 <= bounds[1] <= bounds[3] <= 90
                and math.isfinite(area)
                and area > 0
            )
        except (ValueError, TypeError, KeyError, GEOSException) as exc:
            raise ComputeError("检查结果缺少可核对的修改范围与面积") from exc
        if not valid:
            raise ComputeError("检查结果中的修改范围或面积无效")
        refs = _knowledge(workflow, row, stage["decision"])
        suggestions.append(
            {
                "id": digest({"edit": edit, "knowledge": refs})[:24],
                "kind": edit["kind"],
                "featureId": edit["feature_id"],
                "title": "填补内部漏填"
                if edit["kind"] == "fill_gap"
                else "更新地层时代",
                "currentState": row.get("current_label") or edit["old_value"],
                "suggestedState": row.get("suggested_label") or edit["new_value"],
                "reason": edit["reason"],
                "areaM2": area,
                "ruleId": edit["rule_id"],
                "knowledgeRefs": refs,
                "preview": geometry,
                "bounds": bounds,
            }
        )
    signature = digest(
        {
            "edits": rows,
            "suggestions": suggestions,
            "issues": [
                {"outputId": item["outputId"], "checksum": item["checksum"]}
                for item in results
            ],
        }
    )
    return {
        "proposalHash": signature,
        "suggestions": suggestions,
        "approvedSuggestionIds": [],
    }, rows


def freeze_proposal(workflow, stage):
    review, rows = proposal(workflow, stage, issue_results(workflow))
    workflow.plan["modificationReview"] = review
    stage["proposedEdits"] = rows
    stage["status"] = "needs_review"
    workflow.plan.update(phase="review_modifications", reviewOutputs=[])
    workflow.status, workflow.current_step = "waiting_approval", "review_modifications"
    workflow.detail = "已形成建议修改，请查看依据和修改范围，批准选中的建议后再修正"


def _fresh_proposal(workflow, user, policy, stage):
    check = next(
        item
        for item in workflow.plan["stages"]
        if item["identifier"] == "geology-map-check" and item.get("taskId")
    )
    actual = read_results(
        workflow, user, policy, authorized_task(user, check["taskId"], policy)
    )
    if actual != check["results"]:
        raise ComputeError("检查结果已变化，请重新检查并确认建议", 409)
    review, rows = proposal(
        workflow, stage, [item for item in actual if item["key"] == "issues"]
    )
    stored = workflow.plan.get("modificationReview", {})
    if any(stored.get(key) != review[key] for key in ("proposalHash", "suggestions")):
        raise ComputeError("建议或修改范围已变化，请重新检查并确认", 409)
    return review, rows


def _execution_hash(workflow, stage):
    return digest(
        {
            "inputs": workflow.plan["inputs"],
            "inputSnapshots": workflow.plan["inputSnapshots"],
            "algorithm": workflow.plan["algorithms"][stage["identifier"]],
            "bindings": stage["bindings"],
            "parameters": stage["parameters"],
        }
    )


def approve_modifications(workflow, user, policy, selected, plan_hash):
    from .workflow import step, checkpoint

    if (
        not isinstance(selected, list)
        or not selected
        or any(not isinstance(identity, str) for identity in selected)
        or len(set(selected)) != len(selected)
    ):
        raise ComputeError("请选择需要批准的建议修改", 400)
    stage = workflow.plan["stages"][workflow.plan["stageIndex"]]
    review, rows = _fresh_proposal(workflow, user, policy, stage)
    all_ids = [item["id"] for item in review["suggestions"]]
    if set(selected) - set(all_ids):
        raise ComputeError("所选建议不属于当前计划，请刷新后确认", 409)
    selected = [identity for identity in all_ids if identity in selected]
    approval = {
        "proposalHash": review["proposalHash"],
        "planHash": plan_hash,
        "selectedSuggestionIds": selected,
        "executionHash": _execution_hash(workflow, stage),
    }
    stage["modificationsApproval"] = approval
    stage["approvedEdits"] = [
        row for row, identity in zip(rows, all_ids) if identity in selected
    ]
    workflow.plan["modificationReview"]["approvedSuggestionIds"] = selected
    step(
        workflow,
        "modifications_approved",
        action=approval,
        message="用户已批准选中的建议修改",
        input_refs=workflow.plan["inputs"],
    )
    checkpoint(workflow, "modifications_approved", approval)
    stage["status"] = "pending"


def approved_edits(workflow, user, policy, stage):
    review, rows = _fresh_proposal(workflow, user, policy, stage)
    approval = stage.get("modificationsApproval", {})
    selected = approval.get("selectedSuggestionIds", [])
    ids = [item["id"] for item in review["suggestions"]]
    expected = [row for row, identity in zip(rows, ids) if identity in selected]
    if (
        not selected
        or set(selected) - set(ids)
        or approval.get("proposalHash") != review["proposalHash"]
        or approval.get("executionHash") != _execution_hash(workflow, stage)
        or workflow.plan["modificationReview"]["approvedSuggestionIds"] != selected
        or expected != stage.get("approvedEdits")
        or not workflow.steps.filter(
            kind="modifications_approved", status="succeeded", action=approval
        ).exists()
    ):
        raise ComputeError("修改尚未获得当前范围的用户批准，已停止编辑", 409)
    return [{key: row[key] for key in (*EDIT_FIELDS, "reason")} for row in expected]
