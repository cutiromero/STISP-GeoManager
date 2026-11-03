"""Exact issue/action approval and durable outputs for multi-element reasoning."""

from __future__ import annotations

import csv
import io
import json
import math

from django.db import transaction
from shapely.geometry import shape
from shapely.errors import GEOSException

from apps.catalog.models import DataResource
from apps.compute.access import require_actor
from apps.compute.packages import ComputeError
from apps.core.storage import table_data_path
from apps.knowledge.trial_rules import digest
from .compute_tools import authorized_task
from .demo_results import read_results
from .tools import resolve_resource

CHANGE_FIELDS = (
    "issue_id",
    "feature_id",
    "rule_id",
    "rule_version",
    "snapshot_hash",
    "action",
    "target_code",
    "weight",
    "reason",
)


def check_stage(workflow):
    return next(item for item in workflow.plan["stages"] if item["name"] == "check")


def issue_rows(results):
    return [
        row
        for result in results
        if result["key"] == "issues"
        for row in result.get("rows", [])
    ]


def validate_edits(edits, results):
    if not isinstance(edits, list) or len(edits) > 30:
        raise ComputeError("本轮最多提出30项有依据的对象处置建议")
    issues = {row["issue_id"]: row for row in issue_rows(results)}
    accepted, seen, targets = [], set(), set()
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {
            "issue_id",
            "action",
            "target_code",
            "weight",
            "reason",
        }:
            raise ComputeError("处置建议须明确问题、动作、目标代号、权重及理由")
        if any(
            not isinstance(edit[key], str)
            for key in ("issue_id", "action", "target_code", "reason")
        ) or type(edit["weight"]) not in {int, float}:
            raise ComputeError("处置问题、动作、目标须为文本，权重须为有效数字")
        row = issues.get(edit["issue_id"])
        if row is None or edit["issue_id"] in seen:
            raise ComputeError("建议必须唯一对应本次实际检查的问题")
        target = (row["element"], row["feature_id"])
        if target in targets:
            raise ComputeError("同一对象本轮只允许一个处置动作，请合并相关规则依据")
        try:
            actions = json.loads(row["allowed_actions_json"])
            weight = float(edit["weight"])
        except (ValueError, TypeError, KeyError) as exc:
            raise ComputeError("检查动作或处置权重格式无效") from exc
        action = edit["action"]
        if action not in actions or not math.isfinite(weight) or not 0 <= weight <= 1:
            raise ComputeError("建议超出此对象允许的处置动作或权重范围")
        if (
            (action == "downweight" and not 0 < weight < 1)
            or (action == "exclude" and weight != 0)
            or (action not in {"downweight", "exclude"} and weight != 1)
        ):
            raise ComputeError("降权须保留非零权重，剔除权重为零")
        if action in {"reclassify", "merge", "set_code"}:
            if not edit["target_code"] or str(edit["target_code"]) != str(
                row.get("target_code", "")
            ):
                raise ComputeError("目标代号必须对应本次测量支持的候选类别")
        elif edit["target_code"]:
            raise ComputeError("保留、复核、降权及剔除不允许改变地质类别")
        if (
            not isinstance(edit["reason"], str)
            or not 1 <= len(edit["reason"].strip()) <= 1000
        ):
            raise ComputeError("每项处置须说明实际证据、适用条件和必要例外")
        signature = row.get("snapshot_hash", "")
        if len(signature) != 64 or any(
            char not in "0123456789abcdef" for char in signature
        ):
            raise ComputeError("检查结果缺少有效输入及规则版本签名")
        seen.add(edit["issue_id"])
        targets.add(target)
        accepted.append(
            {
                **{key: str(row[key]) for key in CHANGE_FIELDS[:5]},
                **edit,
                "weight": weight,
            }
        )
    return accepted


def proposal(workflow, stage, results):
    rows = validate_edits(stage.get("edits", []), results)
    issues = {row["issue_id"]: row for row in issue_rows(results)}
    knowledge = {
        (entry["trialBinding"]["ruleId"], entry["trialBinding"]["ruleVersion"]): entry
        for entry in workflow.evidence
        if entry.get("trialBinding")
    }
    cited = {
        ref["id"]
        for ref in stage["decision"]["evidenceRefs"]
        if ref["kind"] == "knowledge"
    }
    suggestions = []
    for edit in rows:
        row = issues[edit["issue_id"]]
        entry = knowledge.get((edit["rule_id"], edit["rule_version"]))
        if entry is None or str(entry["id"]) not in cited:
            raise ComputeError(
                "每项建议须引用对应的实际试用知识及修订，不能只引用其他规则"
            )
        try:
            preview = json.loads(row["geometry_json"])
            geometry = shape(preview)
            if geometry.is_empty or not geometry.is_valid:
                raise ValueError("invalid geometry")
            bounds = list(geometry.bounds)
            if not (
                -180 <= bounds[0] <= bounds[2] <= 180
                and -90 <= bounds[1] <= bounds[3] <= 90
            ):
                raise ValueError("preview must be WGS84")
            measurements = json.loads(row.get("measurements_json") or "{}")
            if not isinstance(measurements, dict):
                raise ValueError("invalid measurements")
        except (ValueError, KeyError, TypeError, GEOSException) as exc:
            raise ComputeError("建议缺少可定位的范围或实际测量值") from exc
        sources = "；".join(
            str(source.get("title", "")) + " " + str(source.get("locator", ""))
            for source in entry["sources"]
        )
        suggestions.append(
            {
                "id": digest(edit)[:24],
                "kind": "multi_element",
                "element": row["element"],
                "featureId": edit["feature_id"],
                "title": row.get("reason", "发现待核查问题")[:100],
                "currentState": row.get("current_state") or "当前识别结果",
                "suggestedState": edit["action"]
                + (" " + edit["target_code"] if edit["target_code"] else ""),
                "reason": edit["reason"],
                "action": edit["action"],
                "status": "review"
                if edit["action"] in {"keep", "review"}
                else "suggested",
                "areaM2": float(
                    measurements.get("involved_area_m2")
                    or row.get("area_m2")
                    or measurements.get("area_m2")
                    or 0
                ),
                "lengthM": float(
                    row.get("length_m") or measurements.get("length_m") or 0
                ),
                "ruleId": edit["rule_id"],
                "observations": measurements,
                "ruleConditions": entry["conditions"],
                "exceptions": entry["exceptions"],
                "ruleRefs": [
                    {
                        "id": edit["rule_id"],
                        "version": edit["rule_version"],
                        "title": entry["title"],
                        "knowledgeId": entry["id"],
                        "revision": entry["revision"],
                        "source": sources,
                    }
                ],
                "knowledgeRefs": [
                    {
                        "id": entry["id"],
                        "revision": entry["revision"],
                        "title": entry["title"],
                    }
                ],
                "preview": preview,
                "bounds": bounds,
            }
        )
    review = {
        "proposalHash": digest(
            {
                "edits": rows,
                "suggestions": suggestions,
                "outputs": [(i["outputId"], i["checksum"]) for i in results],
            }
        ),
        "suggestions": suggestions,
        "approvedSuggestionIds": [],
    }
    return review, rows


def freeze_proposal(workflow, stage):
    review, rows = proposal(workflow, stage, check_stage(workflow)["results"])
    workflow.plan["modificationReview"] = review
    stage["proposedEdits"] = rows
    stage["status"] = "needs_review"
    workflow.plan.update(phase="review_modifications", reviewOutputs=[])
    workflow.status, workflow.current_step = "waiting_approval", "review_modifications"
    workflow.detail = "请选择需要批准的处置；未选中、待裁定项保留，降权仍保留原识别对象"


def _fresh(workflow, user, policy, stage):
    check = check_stage(workflow)
    actual = read_results(
        workflow, user, policy, authorized_task(user, check["taskId"], policy)
    )
    if actual != check["results"]:
        raise ComputeError("实际检查结果已变化，请重新检查并确认", 409)
    review, rows = proposal(workflow, stage, actual)
    if any(
        workflow.plan["modificationReview"].get(key) != review[key]
        for key in ("proposalHash", "suggestions")
    ):
        raise ComputeError("建议的对象、动作或知识版本已变化，须重新确认", 409)
    return review, rows


def execution_hash(workflow, stage):
    return digest(
        {
            "inputs": workflow.plan["inputs"],
            "versions": workflow.plan["inputSnapshots"],
            "algorithm": workflow.plan["algorithms"][stage["identifier"]],
            "rules": workflow.plan["trialRulesSnapshot"],
            "parameters": stage["parameters"],
        }
    )


def approve_modifications(workflow, user, policy, selected, plan_hash):
    from .workflow import step, checkpoint

    if (
        not isinstance(selected, list)
        or any(not isinstance(i, str) for i in selected)
        or len(set(selected)) != len(selected)
    ):
        raise ComputeError("请选择要批准的对象处置建议，可不选择任何修改")
    stage = workflow.plan["stages"][workflow.plan["stageIndex"]]
    review, rows = _fresh(workflow, user, policy, stage)
    ids = [item["id"] for item in review["suggestions"]]
    if set(selected) - set(ids):
        raise ComputeError("所选处置不属于本次方案", 409)
    selected = [identity for identity in ids if identity in selected]
    approval = {
        "proposalHash": review["proposalHash"],
        "planHash": plan_hash,
        "selectedSuggestionIds": selected,
        "executionHash": execution_hash(workflow, stage),
    }
    stage["modificationsApproval"] = approval
    stage["approvedEdits"] = [
        row for row, identity in zip(rows, ids) if identity in selected
    ]
    workflow.plan["modificationReview"]["approvedSuggestionIds"] = selected
    workflow.plan["modificationReview"]["unapprovedSuggestionIds"] = [
        i for i in ids if i not in selected
    ]
    step(
        workflow,
        "modifications_approved",
        action=approval,
        message="已保存所选对象和动作的批准记录；其余保留",
    )
    checkpoint(workflow, "modifications_approved", approval)
    stage["status"] = "pending"


def create_approved_changes(workflow, user, policy, stage):
    from .workflow import step

    require_actor(user, workflow.project_tag_id, "catalog.add_dataresource")
    review, rows = _fresh(workflow, user, policy, stage)
    approval = stage.get("modificationsApproval", {})
    selected = approval.get("selectedSuggestionIds", [])
    ids = [item["id"] for item in review["suggestions"]]
    expected = [row for row, identity in zip(rows, ids) if identity in selected]
    if (
        approval.get("executionHash") != execution_hash(workflow, stage)
        or approval.get("proposalHash") != review["proposalHash"]
        or expected != stage.get("approvedEdits")
        or workflow.plan["modificationReview"]["approvedSuggestionIds"] != selected
        or not workflow.steps.filter(
            kind="modifications_approved", action=approval, status="succeeded"
        ).exists()
    ):
        raise ComputeError("本次对象与动作尚未获得有效批准，已停止处理", 409)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CHANGE_FIELDS)
    writer.writeheader()
    writer.writerows(expected)
    raw = stream.getvalue().encode("utf-8")
    relative = f"demo/workflows/{workflow.id}/approved-changes.csv"
    path = table_data_path(relative)
    source = f"geology-multi-approved:{workflow.id}"
    with transaction.atomic():
        existing = DataResource.objects.filter(source=source).first()
        if existing:
            if not path.is_file() or path.read_bytes() != raw:
                raise ComputeError("已固定的获批操作与当前范围不一致", 409)
            return resolve_resource(user, policy, existing.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        resource = DataResource.objects.create(
            project_tag_id=workflow.project_tag_id,
            name="获批对象处置记录",
            code=f"multi-approved-{workflow.id.hex}",
            data_type="table",
            file_format="CSV",
            storage_path="table/" + relative,
            source=source,
            owner_only=True,
            maintainer=user,
            item_count=len(expected),
            size_bytes=len(raw),
            is_compute_result=True,
        )
        step(
            workflow,
            "approved_changes_fixed",
            message="已将有效批准范围固定为算法输入",
            output_refs={"resourceId": resource.id},
        )
        return resource


def update_map(workflow):
    stages = {
        stage["name"]: {
            output["key"]: output["resourceId"]
            for output in stage.get("outputs", [])
            if output["kind"] == "vector"
        }
        for stage in workflow.plan["stages"]
    }
    apply, check, relations, prospect = (
        stages.get(name, {}) for name in ("apply", "check", "relations", "prospect")
    )
    values = {
        "before": {
            key: workflow.plan["inputs"][key] for key in ("lithology", "faults")
        },
        "checks": [
            value
            for key, value in check.items()
            if key not in {"issues", "statistics", "alterations"}
        ],
    }
    if apply:
        values["after"] = {
            key: apply[key] for key in ("lithology", "faults") if key in apply
        }
        values["changes"] = [value for key, value in apply.items() if "change" in key]
    for key, value in (
        ("beforeAlterations", check.get("alterations")),
        ("alterations", apply.get("alterations") or check.get("alterations")),
        ("beforeIntersections", relations.get("before_intersections")),
        ("intersections", relations.get("intersections")),
        ("beforeProspects", prospect.get("before_zones")),
        ("afterProspects", prospect.get("after_zones")),
    ):
        if value:
            values[key] = value
    workflow.plan["multiElementMap"] = values
