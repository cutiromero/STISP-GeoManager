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
from .workflow_resources import resolve_generated_resource
from .geology_issue_groups import issue_groups

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

MAX_VALIDATION_ERRORS = 30
MAX_VALIDATION_CHARS = 12000


def bounded_errors(errors):
    kept, size, omitted = [], 0, 0
    for error in errors:
        item = {**error, "reason": str(error["reason"])[:800]}
        if "issue_id" in item:
            item["issue_id"] = str(item["issue_id"])[:160]
        length = len(json.dumps(item, ensure_ascii=False))
        if (
            len(kept) < MAX_VALIDATION_ERRORS - 1
            and size + length < MAX_VALIDATION_CHARS - 300
        ):
            kept.append(item)
            size += length
        else:
            omitted += error.get("count", 1)
    if omitted:
        kept.append(
            {
                "index": 0,
                "issue_id": "",
                "count": omitted,
                "reason": f"其余 {omitted} 项无效建议已省略，请按同类原因核对",
            }
        )
    return kept


def _required_knowledge(workflow, decision, issue):
    entry = next(
        (
            entry
            for entry in workflow.evidence
            if entry.get("trialBinding", {}).get("ruleId") == issue["rule_id"]
            and entry["trialBinding"]["ruleVersion"] == issue["rule_version"]
        ),
        None,
    )
    refs = [{"id": entry["id"], "revision": entry["revision"]}] if entry else []
    cited = {
        str(ref["id"]) for ref in decision["evidenceRefs"] if ref["kind"] == "knowledge"
    }
    if entry is None or str(entry["id"]) not in cited:
        required = (
            f"{entry['id']}@{entry['revision']}" if entry else "未检索到对应试用知识"
        )
        error = ComputeError(
            f"缺少该规则 {issue['rule_id']}@{issue['rule_version']} 对应的实际试用知识及修订引用：{required}；不能只引用其他规则"
        )
        error.required_knowledge_refs = refs
        raise error
    return entry


def check_stage(workflow):
    return next(item for item in workflow.plan["stages"] if item["name"] == "check")


def issue_rows(results):
    return [
        row
        for result in results
        if result["key"] == "issues"
        for row in result.get("rows", [])
    ]


class EditValidationError(ComputeError):
    def __init__(self, errors):
        self.errors = bounded_errors(errors)
        super().__init__(
            "；".join(
                item["reason"]
                if "group_id" in item or item["index"] == 0
                else f"第{item['index']}项（issue_id={item['issue_id']}）：{item['reason']}"
                for item in self.errors
            )
        )


def _canonical_review_group(original, members):
    required = {"group_id", "disposition", "excluded_issue_ids", "reason"}
    redundant = {"action", "target_code", "weight"}
    if not required <= set(original):
        raise ComputeError(
            "分组建议须含group_id、disposition、excluded_issue_ids及reason"
        )
    extras = set(original) - required
    if extras - redundant:
        raise ComputeError("分组建议包含未知字段，只允许四个必需字段及等价的动作字段")
    canonical = {key: original[key] for key in required}
    if not extras:
        return canonical
    excluded = original["excluded_issue_ids"]
    if (
        not isinstance(excluded, list)
        or any(not isinstance(item, str) for item in excluded)
        or set(excluded) - {row["issue_id"] for row in members}
    ):
        raise ComputeError("分组或排除对象不属于本次检查快照")
    disposition = original["disposition"]
    if not isinstance(disposition, str) or disposition not in {
        "suggested",
        "keep",
        "review",
    }:
        raise ComputeError("拒绝候选不产生动作，或分组处置无效；不得附加动作字段")
    included = [row for row in members if row["issue_id"] not in excluded]
    if not included:
        raise ComputeError("空处置范围不能证明冗余动作字段与成员处置等价")
    if ("action" in extras and not isinstance(original["action"], str)) or (
        "target_code" in extras and not isinstance(original["target_code"], str)
    ):
        raise ComputeError("分组冗余动作和目标须为文本")
    if "weight" in extras and (
        type(original["weight"]) not in {int, float}
        or type(original["weight"]) is float
        and not math.isfinite(original["weight"])
    ):
        raise ComputeError("分组冗余权重须为有限数值，不接受布尔值或文本")
    for row in included:
        action = row["suggested_action"] if disposition == "suggested" else disposition
        expected = {
            "action": action,
            "target_code": row.get("target_code", "")
            if action in {"set_code", "merge", "reclassify"}
            else "",
            "weight": 0.5
            if action == "downweight"
            else 0
            if action == "exclude"
            else 1,
        }
        if any(original[key] != expected[key] for key in extras):
            raise ComputeError("分组冗余动作字段与纳入成员的确定性处置不一致")
    return canonical


def _expand_review_group(original, members):
    """Validate a model group, then expand only its complete real member scope."""
    from .geology_issue_groups import expand_groups

    original = _canonical_review_group(original, members)
    actual = issue_groups(members)
    if not actual:
        return expand_groups([original], members)
    # Reuse the established field/reason validation without weakening it for
    # model aggregation IDs, which may cover several real raster unit IDs.
    probe = {
        **original,
        "group_id": actual[0][0],
        "disposition": "review",
        "excluded_issue_ids": [],
    }
    expand_groups([probe], actual[0][1])
    excluded = original.get("excluded_issue_ids")
    disposition = original.get("disposition")
    if (
        not isinstance(excluded, list)
        or any(not isinstance(item, str) for item in excluded)
        or set(excluded) - {row["issue_id"] for row in members}
    ):
        raise ComputeError("分组或排除对象不属于本次检查快照")
    if disposition not in ("suggested", "keep", "review", "reject"):
        raise ComputeError("整组处置只能采用建议、保留、待裁定或拒绝")
    if disposition in {"review", "reject"}:
        return []
    if disposition == "keep":
        return [
            {
                "issue_id": row["issue_id"],
                "action": "keep",
                "target_code": "",
                "weight": 1,
                "reason": original["reason"],
            }
            for row in members
            if row["issue_id"] not in excluded
        ]
    expanded = []
    for identity, rows in actual:
        ids = {row["issue_id"] for row in rows}
        expanded.extend(
            expand_groups(
                [
                    {
                        **original,
                        "group_id": identity,
                        "excluded_issue_ids": [
                            item for item in excluded if item in ids
                        ],
                    }
                ],
                rows,
            )
        )
    return expanded


def assess_edits(edits, results, *, workflow=None, decision=None, model_payload=None):
    if not isinstance(edits, list):
        raise ComputeError("处置建议须为数组")
    issues = {row["issue_id"]: row for row in issue_rows(results)}
    groups = dict(issue_groups(list(issues.values())))
    if model_payload is not None:
        from .demo_decision_batches import model_issue_groups

        groups.update(model_issue_groups(list(issues.values())))
    accepted, errors, duplicates = [], [], []
    discarded, raster_errors = 0, 0
    raster_issue_ids = {
        identity
        for identity, row in issues.items()
        if row.get("element") == "alteration"
        and str(row.get("feature_id", "")).startswith("AG-")
    }
    raster_group_ids = {
        identity
        for identity, members in groups.items()
        if any(row["issue_id"] in raster_issue_ids for row in members)
    }
    normalized, seen, targets = set(), set(), set()

    def record_error(index, original, exc, count=1):
        nonlocal discarded, errors, raster_errors
        discarded += count
        grouped = isinstance(original, dict) and "group_id" in original
        if isinstance(original, dict) and (
            isinstance(original.get("group_id"), str)
            and original["group_id"] in raster_group_ids
            or isinstance(original.get("issue_id"), str)
            and original["issue_id"] in raster_issue_ids
        ):
            raster_errors += count
        reason = str(exc)
        if grouped:
            members = (
                groups.get(original["group_id"], [])
                if isinstance(original["group_id"], str)
                else []
            )
            rule = members[0]["rule_id"] if members else str(original["group_id"])[:100]
            action = (
                members[0]["suggested_action"]
                if members
                else str(original.get("disposition", ""))
            )
            reason = f"组 {rule}/{action}（{count} 个对象）：{reason}"
        item = {
            "index": index,
            "issue_id": original.get("issue_id", "")
            if isinstance(original, dict)
            else "",
            "reason": reason,
            **(
                {"group_id": str(original["group_id"])[:100], "count": count}
                if grouped
                else {}
            ),
        }
        if hasattr(exc, "required_knowledge_refs"):
            item["requiredKnowledgeRefs"] = exc.required_knowledge_refs
        errors = bounded_errors([*errors, item])

    def validate_one(index, original, entry):
        edit = original.copy() if isinstance(original, dict) else original
        if (
            isinstance(edit, dict)
            and edit.get("action") in ("keep", "review", "downweight", "exclude")
            and "target_code" in edit
        ):
            edit["target_code"] = ""
        signature = json.dumps(edit, sort_keys=True, ensure_ascii=False)
        if signature in normalized:
            duplicates.append(index)
            return
        row = _validate_edit_rows([edit], results, issues=issues)[0]
        if row["issue_id"] in seen:
            raise ComputeError("建议必须唯一对应本次实际检查的问题")
        issue = issues[row["issue_id"]]
        target = (issue["element"], issue["feature_id"])
        if target in targets:
            raise ComputeError("同一对象本轮只允许一个处置动作，保留首个合格建议")
        if workflow is not None:
            proposal(
                workflow,
                {"edits": [edit], "decision": decision},
                results,
                issues={issue["issue_id"]: issue},
                knowledge_entry=entry,
            )
        normalized.add(signature)
        seen.add(row["issue_id"])
        targets.add(target)
        accepted.append(row)

    seen_groups, pending = set(), []
    for index, original in enumerate(edits, 1):
        grouped = isinstance(original, dict) and "group_id" in original
        entry = None
        try:
            if model_payload is not None:
                from .decision_budget import assert_visible_edits

                try:
                    assert_visible_edits([original], model_payload)
                except ValueError as exc:
                    raise ComputeError(str(exc)) from exc
            if grouped and isinstance(original["group_id"], str):
                if original["group_id"] in seen_groups:
                    raise ComputeError("同一分组只能给出一次处置")
                seen_groups.add(original["group_id"])
            expanded = (
                _expand_review_group(
                    original,
                    groups.get(original["group_id"], [])
                    if isinstance(original["group_id"], str)
                    else [],
                )
                if grouped
                else [original]
            )
            if grouped and expanded and workflow is not None:
                entry = _required_knowledge(
                    workflow, decision, issues[expanded[0]["issue_id"]]
                )
        except ComputeError as exc:
            members = (
                groups.get(original.get("group_id"), [])
                if grouped and isinstance(original.get("group_id"), str)
                else []
            )
            excluded = original.get("excluded_issue_ids", []) if grouped else []
            count = (
                sum(row["issue_id"] not in excluded for row in members)
                if isinstance(excluded, list)
                else len(members)
            )
            record_error(index, original, exc, max(1, count))
            continue
        if grouped:
            pending.extend((index, original, edit, entry) for edit in expanded)
            continue
        for expanded_edit in expanded:
            try:
                validate_one(index, expanded_edit, entry)
            except ComputeError as exc:
                record_error(index, original, exc)
    issue_order = {identity: index for index, identity in enumerate(issues)}
    group_errors, group_targets = {}, set()
    for index, original, edit, entry in sorted(
        pending, key=lambda item: issue_order[item[2]["issue_id"]]
    ):
        issue = issues[edit["issue_id"]]
        target = (issue["element"], issue["feature_id"])
        if target in group_targets:
            continue
        group_targets.add(target)
        try:
            validate_one(index, edit, entry)
        except ComputeError as exc:
            key = (index, str(exc))
            previous = group_errors.get(key, (original, exc, 0))
            group_errors[key] = (original, exc, previous[2] + 1)
    for (index, _), (original, exc, count) in group_errors.items():
        record_error(index, original, exc, count)
    return accepted, {
        "discardedCount": discarded,
        "errors": errors,
        "duplicateCount": len(duplicates),
        "duplicateIndices": duplicates,
        **({"unreviewedRasterCount": raster_errors} if raster_errors else {}),
    }


def validate_edits(edits, results):
    rows, assessment = assess_edits(edits, results)
    if assessment["errors"]:
        raise EditValidationError(assessment["errors"])
    return rows


def _validate_edit_rows(edits, results, *, issues=None):
    if not isinstance(edits, list):
        raise ComputeError("处置建议须为数组")
    if issues is None:
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
        if row["status"] in {"review", "exception"} and action not in {
            "keep",
            "review",
        }:
            raise ComputeError(
                "模型不得替用户处置待裁定或例外对象；请保留，候选由用户独立选择"
            )
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


def proposal(workflow, stage, results, *, issues=None, knowledge_entry=None):
    if issues is None:
        issues = {row["issue_id"]: row for row in issue_rows(results)}
    rows = _validate_edit_rows(stage.get("edits", []), results, issues=issues)
    rows = [
        row
        for row in rows
        if issues[row["issue_id"]]["status"] not in {"review", "exception"}
    ]
    for issue in issues.values():
        action = issue.get("candidate_action")
        if issue["status"] not in {"review", "exception"} or not action:
            continue
        if action not in json.loads(issue["allowed_actions_json"]) or (
            action == "reclassify" and not issue.get("candidate_target_code")
        ):
            raise ComputeError("检查快照中的候选动作或目标无效")
        rows.append(
            {
                **{key: str(issue[key]) for key in CHANGE_FIELDS[:5]},
                "action": action,
                "target_code": issue.get("candidate_target_code", ""),
                "weight": 0
                if action == "exclude"
                else 0.5
                if action == "downweight"
                else 1,
                "reason": issue["reason"],
            }
        )
    suggestions = []
    group_ids = {
        row["issue_id"]: identity
        for identity, members in issue_groups(list(issues.values()))
        for row in members
    }
    for edit in rows:
        row = issues[edit["issue_id"]]
        held = row["status"] in {"review", "exception"}
        if held:
            entry = next(
                (
                    entry
                    for entry in workflow.evidence
                    if entry.get("trialBinding", {}).get("ruleId") == row["rule_id"]
                    and entry["trialBinding"]["ruleVersion"] == row["rule_version"]
                ),
                None,
            )
            if entry is None:
                raise ComputeError("候选处置缺少本次规则对应的知识修订")
        else:
            entry = knowledge_entry or _required_knowledge(
                workflow, stage["decision"], edit
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
                "groupId": group_ids[edit["issue_id"]],
                "kind": "multi_element",
                "element": row["element"],
                "featureId": edit["feature_id"],
                "title": row.get("reason", "发现待核查问题")[:100],
                "currentState": row.get("current_state") or "当前识别结果",
                "suggestedState": edit["action"]
                + (" " + edit["target_code"] if edit["target_code"] else ""),
                "reason": edit["reason"],
                "action": edit["action"],
                "status": row["status"]
                if held
                else "review"
                if edit["action"] in {"keep", "review"}
                else "suggested",
                "origin": "operator_held_candidate" if held else "model_reviewed",
                "allowedActions": json.loads(row["allowed_actions_json"]),
                **(
                    {
                        "candidateAction": edit["action"],
                        "candidateTargetCode": edit["target_code"],
                    }
                    if held
                    else {}
                ),
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
        workflow,
        user,
        policy,
        authorized_task(user, check["taskId"], policy, workflow=workflow),
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


def approve_modifications(
    workflow, user, policy, selected, plan_hash, alteration_actions=None
):
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
    selected_set = set(selected)
    selected = [identity for identity in ids if identity in selected_set]
    actions = validate_alteration_actions(
        review, selected_set, {} if alteration_actions is None else alteration_actions
    )
    approval = {
        "proposalHash": review["proposalHash"],
        "planHash": plan_hash,
        "selectedSuggestionIds": selected,
        "executionHash": execution_hash(workflow, stage),
        **({"alterationActions": actions} if actions else {}),
    }
    targets = [
        (row["element"], row["featureId"])
        for row in review["suggestions"]
        if row["id"] in selected_set
    ]
    if len(set(targets)) != len(targets):
        raise ComputeError("同一对象只能选择一个候选或建议处置")
    stage["modificationsApproval"] = approval
    stage["approvedEdits"] = selected_edits(rows, review, selected, actions)
    workflow.plan["modificationReview"]["approvedSuggestionIds"] = selected
    workflow.plan["modificationReview"]["unapprovedSuggestionIds"] = [
        i for i in ids if i not in selected_set
    ]
    step(
        workflow,
        "modifications_approved",
        action=approval,
        message="已保存所选对象和动作的批准记录；其余保留",
    )
    checkpoint(workflow, "modifications_approved", approval)
    stage["status"] = "pending"


def validate_alteration_actions(review, selected, actions):
    if not isinstance(actions, dict):
        raise ComputeError("蚀变组动作须为分组到动作的映射")
    allowed = {
        item["featureId"]: set(item.get("allowedActions", []))
        & {"keep", "downweight", "exclude"}
        for item in review["suggestions"]
        if item["id"] in selected
        and item.get("element") == "alteration"
        and item.get("featureId", "").startswith("AG-")
    }
    if set(actions) - set(allowed) or any(
        not isinstance(action, str) or action not in allowed.get(identity, set())
        for identity, action in actions.items()
    ):
        raise ComputeError("蚀变组动作超出本次已选择的冻结组或允许动作", 409)
    return actions


def selected_edits(rows, review, selected, actions=None):
    selected = set(selected)
    edits = [
        {**row, "reason": "用户裁定（规则为待裁定/例外）：" + row["reason"]}
        if suggestion.get("candidateAction")
        else row
        for row, suggestion in zip(rows, review["suggestions"])
        if suggestion["id"] in selected
    ]
    return [
        {
            **row,
            "action": actions[row["feature_id"]],
            "weight": {"keep": 1, "downweight": 0.5, "exclude": 0}[
                actions[row["feature_id"]]
            ],
            "reason": f"用户显式裁定蚀变组动作（原{row['action']}，现{actions[row['feature_id']]}）；原理由："
            + row["reason"],
        }
        if actions and row["feature_id"] in actions
        else row
        for row in edits
    ]


def create_approved_changes(workflow, user, policy, stage):
    from .workflow import step

    require_actor(user, workflow.project_tag_id, "catalog.add_dataresource")
    review, rows = _fresh(workflow, user, policy, stage)
    approval = stage.get("modificationsApproval", {})
    selected = approval.get("selectedSuggestionIds", [])
    actions = validate_alteration_actions(
        review, set(selected), approval.get("alterationActions", {})
    )
    expected = selected_edits(rows, review, selected, actions)
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
            return resolve_generated_resource(
                user, policy, existing.id, workflow, "approved_changes"
            )
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
        clean_outputs = (
            workflow.plan.get("algorithms", {})
            .get("geology-multi-apply", {})
            .get("manifest", {})
            .get("outputs", [])
        )
        clean_results = any(item["key"] == "final_faults" for item in clean_outputs)
        if clean_results:
            values["after"].pop("faults", None)
            if apply.get("final_faults"):
                values["after"]["faults"] = apply["final_faults"]
        values["changes"] = [value for key, value in apply.items() if "change" in key]
    for key, value in (
        ("beforeAlterations", check.get("alterations")),
        (
            "alterations",
            apply.get("final_alterations")
            if apply and clean_results
            else apply.get("alterations") or check.get("alterations"),
        ),
        ("beforeIntersections", relations.get("before_intersections")),
        ("intersections", relations.get("intersections")),
        ("beforeProspects", prospect.get("before_zones")),
        ("afterProspects", prospect.get("after_zones")),
    ):
        if value:
            values[key] = value
    workflow.plan["multiElementMap"] = values
    check_outputs = {
        item["key"]: item["outputId"]
        for stage in workflow.plan["stages"]
        if stage["name"] == "check"
        for item in stage.get("results", [])
        if item.get("outputId")
    }
    apply_outputs = {
        item["key"]: item["outputId"]
        for stage in workflow.plan["stages"]
        if stage["name"] == "apply"
        for item in stage.get("results", [])
        if item.get("outputId")
    }
    rasters = []
    for mineral in ("hematite", "chlorite", "hydromica", "calcite", "dolomite"):
        if mineral + "_before" not in check_outputs:
            continue
        entry = {
            "mineral": mineral,
            "beforeOutputId": check_outputs[mineral + "_before"],
        }
        for field, suffix in (
            ("afterOutputId", "corrected"),
            ("changesOutputId", "changes"),
        ):
            if mineral + "_" + suffix in apply_outputs:
                entry[field] = apply_outputs[mineral + "_" + suffix]
        rasters.append(entry)
    if rasters:
        values["alterationRasters"] = rasters
