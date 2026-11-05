"""Sequential, resumable model review of complete, snapshot-bound member scopes."""

import copy
import hashlib
import json

from apps.compute.packages import ComputeError
from .config import registry
from .decision_budget import BudgetReviewRequired, _expand_knowledge
from .geology_issue_groups import group_summaries, issue_groups

# Configuration: request size adapts downward through the real tokenizer gate.
MAX_BATCH_ROWS = 128
MAX_BATCH_GROUPS = 8
SOURCE_POLICY_KEYS = (
    "maxContextTokens",
    "maxContextBytes",
    "maxOutputTokens",
    "reasoningEffort",
    "_thinking",
    "temperature",
    "topP",
)


def signature(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def scope_signature(scope):
    return signature([(item["outputId"], index, row) for item, index, row in scope])


def review_issues(workflow, results):
    check = next(
        (item for item in workflow.plan["stages"] if item["name"] == "check"), {}
    )
    return [
        (result, index, row)
        for result in results
        if result["key"] == "issues" and result.get("taskId") == check.get("taskId")
        for index, row in enumerate(result.get("rows", []))
    ]


def model_issue_groups(rows):
    """AG rows already describe complete raster units; retain every such unit."""
    vector, raster = [], {}
    for row in rows:
        if row.get("element") != "alteration" or not str(
            row.get("feature_id", "")
        ).startswith("AG-"):
            vector.append(row)
            continue
        measured = json.loads(row.get("measurements_json") or "{}")
        key = tuple(
            row.get(name, "")
            for name in (
                "rule_id",
                "rule_version",
                "suggested_action",
                "target_code",
                "status",
                "snapshot_hash",
            )
        ) + tuple(
            json.dumps(measured.get(name, ""), sort_keys=True)
            for name in ("mineral", "rock_group", "boundary")
        )
        raster.setdefault(key, []).append(row)
    return [
        *issue_groups(vector),
        *[("AGB-" + signature(key)[:24], members) for key, members in raster.items()],
    ]


def model_group_summaries(rows):
    summaries = []
    for identity, members in model_issue_groups(rows):
        parts = group_summaries(members)
        value = {**parts[0], "group_id": identity, "count": len(members)}
        if identity.startswith("AGB-"):
            ranges = {}
            for part in parts:
                for name, bounds in part["measurementRanges"].items():
                    current = ranges.setdefault(name, list(bounds))
                    current[:] = [
                        min(current[0], bounds[0]),
                        max(current[1], bounds[1]),
                    ]
            value.update(
                measurementRanges=ranges, modelGroupKind="complete_raster_units"
            )
        summaries.append(value)
    return summaries


def raster_disposition_scope(payload, edits):
    groups = {
        group["group_id"]: group
        for result in payload.get("actualResults", [])
        if result.get("key") == "issues"
        for group in result.get("groups", [])
        if group.get("modelGroupKind") == "complete_raster_units"
    }
    group_ids = {
        edit["group_id"]
        for edit in edits
        if isinstance(edit, dict) and isinstance(edit.get("group_id"), str)
    }
    individual = {
        edit["issue_id"]
        for edit in edits
        if isinstance(edit, dict) and isinstance(edit.get("issue_id"), str)
    }
    missing = [
        identity
        for identity, group in groups.items()
        if identity not in group_ids
        and any(row["issue_id"] not in individual for row in group["samples"])
    ]
    if missing:
        raise ComputeError(
            f"本批{len(missing)}个蚀变聚合组尚未明确处置；逐组输出suggested、keep、review或reject，不能省略后由算子补齐"
        )
    return set(groups), {
        row["issue_id"] for group in groups.values() for row in group["samples"]
    }


def needs_batches(workflow, stage, results):
    if stage["identifier"] != "geology-multi-apply":
        return False
    rows = [row for _, _, row in review_issues(workflow, results)]
    groups = model_issue_groups(rows)
    return (
        bool(stage.get("modelBatches"))
        or any(str(row.get("feature_id", "")).startswith("AG-") for row in rows)
        or len(groups) > MAX_BATCH_GROUPS
        or any(len(members) > 3 for _, members in groups)
    )


def scoped_results(results, scope):
    selected = {(str(result["outputId"]), index) for result, index, _ in scope}
    return [
        {
            **item,
            "rows": [
                row
                for index, row in enumerate(item.get("rows", []))
                if (str(item["outputId"]), index) in selected
            ],
        }
        if item["key"] == "issues"
        else item
        for item in results
    ]


def batch_payload(payload, results, scope, batch_index):
    """Every member is visible; a group refers only to this request's scope."""
    value = _expand_knowledge(payload)
    selected = {}
    sources = {}
    for result, index, row in scope:
        member = {key: cell for key, cell in row.items() if key != "geometry_json"}
        sources[str(result["outputId"])] = {
            "outputId": result["outputId"],
            "checksum": result.get("checksum"),
            "geometryStoredInOriginal": True,
        }
        member["sourceRowIndex"] = index
        selected.setdefault(str(result["outputId"]), []).append(member)
    rules = {row["rule_id"] for _, _, row in scope}
    value["knowledge"] = [
        entry
        for entry in value["knowledge"]
        if not entry.get("trialBinding", {}).get("ruleId")
        or entry["trialBinding"]["ruleId"] in rules
    ]
    knowledge_ids = {str(entry["id"]) for entry in value["knowledge"]}
    value["availableEvidence"] = [
        ref
        for ref in value["availableEvidence"]
        if ref["kind"] != "knowledge" or str(ref["id"]) in knowledge_ids
    ]
    for result in value["actualResults"]:
        if result["key"] != "issues":
            continue
        members = selected.get(str(result["outputId"]), [])
        groups = model_group_summaries(members)
        members_by_group = dict(model_issue_groups(members))
        for group in groups:
            group_members = members_by_group[group["group_id"]]
            common = {
                key: cell
                for key, cell in group_members[0].items()
                if key not in {"issue_id", "feature_id", "sourceRowIndex"}
                and all(member.get(key) == cell for member in group_members)
            }
            group["memberCommon"] = common
            group["memberSource"] = sources[str(result["outputId"])]
            group["samples"] = [
                {key: cell for key, cell in member.items() if key not in common}
                for member in group_members
            ]
            group["memberCoverage"] = "complete_batch_members"
        result.update(rows=[], groups=groups, scope="complete_batch_members")
    for role in value["inputRoles"]:
        if role.get("role") == "rules":
            role["rows"] = [
                row for row in role.get("rows", []) if row.get("rule_id") in rules
            ]
    value["modelBatch"] = {
        "index": batch_index,
        "completeMembers": True,
        "memberCount": len(scope),
        "scopeSha256": scope_signature(scope),
        "instruction": "本批groups的samples包含全部本批成员。group_id仅在本批范围展开；"
        "每个成员继承该组memberCommon的完全相同原值；memberSource与sourceRowIndex定位原始行。"
        "逐成员核对必要测量、知识条件及例外，不能把本批建议扩大到其余同组对象。",
    }
    return value


def _end_offset(rows, offset):
    end = min(len(rows), offset + MAX_BATCH_ROWS)
    for candidate in range(offset + 1, end + 1):
        if (
            len(model_issue_groups([row for _, _, row in rows[offset:candidate]]))
            > MAX_BATCH_GROUPS
        ):
            return candidate - 1
    return end


def _merged_decision(batches, edits, total):
    decisions = [batch["stage"]["decision"] for batch in batches]
    basis = next(
        (
            item
            for item in reversed(decisions)
            if edits and item["nextAction"] == "geology-multi-apply"
        ),
        decisions[-1],
    )
    value = copy.deepcopy(basis)
    refs, seen = [], set()
    for decision in decisions:
        for ref in decision["evidenceRefs"]:
            key = json.dumps(ref, sort_keys=True)
            if key not in seen:
                refs.append(ref)
                seen.add(key)
    value["evidenceRefs"] = refs
    note = f"已完成{len(batches)}批、{total}条候选记录的证据检视；形成{len(edits)}项待用户批准的逐对象建议。"
    value["findings"] = [note, *value["findings"]]
    value["resultSummary"] = note + "\n" + value["resultSummary"]
    if any(item["nextAction"] == "request_review" for item in decisions):
        value["uncertainties"].append(
            "部分批次仍需补充证据，未形成有据修改的对象保持原样。"
        )
    if edits:
        value["nextAction"] = "geology-multi-apply"
    return value


def batch_source(workflow, policy, stage, results, context):
    return signature(
        {
            "batchProtocol": "complete_vector_and_raster_units_v2",
            "results": results,
            "context": context,
            "knowledge": workflow.evidence,
            "goal": workflow.goal,
            "workflowType": workflow.workflow_type,
            "upstreamVersions": workflow.plan.get("upstreamVersions"),
            "confirmedMapping": workflow.plan.get("confirmedMapping"),
            "inputs": workflow.plan.get("inputs"),
            "rules": workflow.plan.get("trialRuleBindings"),
            "algorithm": workflow.plan.get("algorithms"),
            "model": {
                "alias": workflow.model,
                "id": registry()[workflow.model].model_id,
            },
            "stage": {
                key: stage.get(key)
                for key in ("name", "identifier", "bindings", "parameters")
            },
            "policy": {key: policy.get(key) for key in SOURCE_POLICY_KEYS},
        }
    )


def plan_batches(workflow, user, policy, stage, results, guard, context=None):
    """Use the serving tokenizer and production request builder, without generation."""
    from .demo_decisions import _decide_once
    from .demo_results import resource_context

    context = resource_context(workflow, user, policy) if context is None else context
    rows, planned, offset = review_issues(workflow, results), [], 0
    source = batch_source(workflow, policy, stage, results, context)
    while offset < len(rows):
        end = _end_offset(rows, offset)
        lower, upper, best = offset + 1, end, None
        while lower <= upper:
            guard()
            scope = rows[offset:end]
            child = {
                key: copy.deepcopy(stage[key])
                for key in ("name", "identifier", "bindings", "parameters")
                if key in stage
            }
            try:
                measured = _decide_once(
                    workflow,
                    user,
                    policy,
                    child,
                    results,
                    guard,
                    _context=context,
                    _batch=(scope, len(planned) + 1),
                    _preflight=True,
                )
            except BudgetReviewRequired:
                if end - offset == 1 and best is None:
                    for key in (
                        "contextBudgetReview",
                        "modelRequestPayload",
                        "modelRequestInstruction",
                    ):
                        if key in child:
                            stage[key] = copy.deepcopy(child[key])
                    stage.setdefault("contextBudgetReview", {}).update(
                        kind="input_budget",
                        preflight=True,
                        requested=False,
                    )
                    raise
                upper = end - 1
            else:
                best = {
                    "start": offset,
                    "end": end,
                    "scopeSha256": scope_signature(scope),
                    **measured,
                }
                lower = end + 1
            end = (lower + upper) // 2
        if best is None:
            raise BudgetReviewRequired("单条聚合证据仍超预算，未发送模型请求")
        planned.append(best)
        offset = best["end"]
    value = {"sourceSha256": source, "memberCount": len(rows), "batches": planned}
    return {**value, "planSha256": signature(value)}


def run_batches(
    single,
    workflow,
    user,
    policy,
    stage,
    results,
    context,
    guard,
    on_attempt=None,
    on_response=None,
    **callbacks,
):
    rows = review_issues(workflow, results)
    source = batch_source(workflow, policy, stage, results, context)
    state = stage.setdefault(
        "modelBatches",
        {
            "sourceSha256": source,
            "cursor": 0,
            "batches": [],
            "status": "running",
            "memberCount": len(rows),
        },
    )
    if not isinstance(state, dict) or state.get("sourceSha256") != source:
        raise ComputeError(
            "分批证据、规则、输入版本或模型预算已变化，已保留原审计；请重新发起分析"
        )
    if (
        not isinstance(state.get("batches"), list)
        or type(state.get("cursor")) is not int
        or not 0 <= state["cursor"] <= len(state["batches"]) <= state["cursor"] + 1
        or state.get("memberCount") != len(rows)
    ):
        raise ComputeError("分批分析游标无效，已停止恢复")
    preflight = state.get("preflight")
    if preflight is not None:
        if (
            not isinstance(preflight, dict)
            or preflight.get("sourceSha256") != source
            or preflight.get("planSha256")
            != signature(
                {key: value for key, value in preflight.items() if key != "planSha256"}
            )
        ):
            raise ComputeError("分批预算规划与本次证据不一致，请重新核查预算")
        end = 0
        for item in preflight.get("batches", []):
            if (
                type(item.get("end")) is not int
                or item.get("start") != end
                or not end < item["end"] <= len(rows)
                or item.get("scopeSha256") != scope_signature(rows[end : item["end"]])
            ):
                raise ComputeError("分批预算规划范围无效")
            end = item["end"]
        if end != len(rows):
            raise ComputeError("分批预算规划未覆盖全部证据")
    offset, edits, seen = 0, [], set()
    targets = {
        row["issue_id"]: (row["element"], row["feature_id"]) for _, _, row in rows
    }

    def merge(proposed):
        for edit in proposed:
            target = targets[edit["issue_id"]]
            if target not in seen:
                edits.append(edit)
                seen.add(target)

    def valid_range(batch, start):
        return (
            isinstance(batch, dict)
            and type(batch.get("start")) is int
            and type(batch.get("end")) is int
            and batch["start"] == start
            and start < batch["end"] <= len(rows)
        )

    for index, batch in enumerate(state["batches"][: state["cursor"]]):
        if not valid_range(batch, offset) or batch.get("status") != "complete":
            raise ComputeError("分批完成范围不连续，已停止恢复")
        scope = rows[offset : batch["end"]]
        if batch.get("scopeSha256") != scope_signature(scope) or not batch["stage"].get(
            "decision"
        ):
            raise ComputeError("分批证据或已保存判断发生变化，已停止恢复")
        recovered_stage = copy.deepcopy(batch["stage"])
        recovered_stage.pop("decision")
        recovered = single(
            workflow,
            user,
            policy,
            recovered_stage,
            results,
            guard,
            _context=context,
            _batch=(scope, index + 1),
        )
        if recovered != (batch["stage"]["decision"], batch["stage"]["edits"]):
            raise ComputeError("已完成批次与实际模型响应不一致，已停止恢复")
        merge(batch["stage"]["edits"])
        offset = batch["end"]
    while offset < len(rows):
        guard()
        index = state["cursor"]
        if len(state["batches"]) > index:
            batch = state["batches"][index]
        else:
            batch = {
                "start": offset,
                "end": preflight["batches"][index]["end"]
                if preflight
                else _end_offset(rows, offset),
                "status": "pending",
                "stage": {
                    key: copy.deepcopy(value)
                    for key, value in stage.items()
                    if key
                    not in {
                        "modelBatches",
                        "modelAttempts",
                        "modelRequestPayload",
                        "modelRequestInstruction",
                        "contextBudgetReview",
                    }
                },
            }
            state["batches"].append(batch)
        if not valid_range(batch, offset):
            raise ComputeError("待恢复分批范围与实际证据不一致")
        scope = rows[offset : batch["end"]]
        scope_hash = scope_signature(scope)
        if (
            batch.get("start") != offset
            or not scope
            or batch.get("scopeSha256", scope_hash) != scope_hash
        ):
            raise ComputeError("待恢复分批范围与实际证据不一致")
        batch["scopeSha256"] = scope_hash
        child = batch["stage"]
        attempts = child.get("modelAttempts", [])
        if (
            attempts
            and attempts[-1].get("status") == "budget_blocked"
            and attempts[-1].get("requested") is False
        ):
            if stage.get("contextBudgetReview"):
                raise BudgetReviewRequired(
                    "分批分析等待用户调整真实调用预算；已完成进度保留"
                )
            child.setdefault("unrequestedBudgetAttempts", []).append(attempts.pop())
            if not attempts:
                child.pop("modelAttempts", None)
            elif attempts[-1].get("status") == "rejected":
                raise ComputeError(
                    "本批原响应已被校验拒绝，修正请求因额度不足尚未发送；"
                    "已保留原响应和额度阻断审计，请核对后重新发起分析"
                )

        def record(attempt):
            attempt["batchIndex"] = index + 1
            if on_attempt:
                on_attempt(attempt)
            elif attempt["status"] == "requesting":
                attempt["requested"] = True

        def response():
            if on_response:
                on_response(child["modelAttempts"][-1])

        try:
            decision, proposed = single(
                workflow,
                user,
                policy,
                child,
                results,
                guard,
                record,
                response if on_response else None,
                _context=context,
                _batch=(scope, index + 1),
                **callbacks,
            )
        except BudgetReviewRequired:
            if not preflight and not child.get("modelAttempts") and len(scope) > 1:
                batch["end"] = offset + max(1, len(scope) // 2)
                batch.pop("scopeSha256", None)
                for key in (
                    "contextBudgetReview",
                    "modelRequestPayload",
                    "modelRequestInstruction",
                ):
                    child.pop(key, None)
                continue
            state["status"] = "paused"
            stage["contextBudgetReview"] = {
                "reason": "本批必要证据超出输入预算",
                "batchIndex": index + 1,
            }
            raise
        except ComputeError as exc:
            state["status"] = "paused"
            if "真实模型请求次数上限" in str(exc):
                stage["contextBudgetReview"] = {
                    "reason": str(exc),
                    "batchIndex": index + 1,
                    "kind": "model_call_limit",
                    "requested": False,
                }
                raise BudgetReviewRequired(
                    f"分批分析已覆盖{offset}/{len(rows)}个对象，达到真实模型请求次数上限；进度和审计已保留。"
                ) from exc
            raise
        except Exception:
            state["status"] = "interrupted"
            raise
        child.update(decision=decision, edits=proposed)
        batch["status"] = "complete"
        merge(proposed)
        offset = batch["end"]
        state.update(cursor=index + 1, coveredMemberCount=offset)
        if child.get("modelAttempts") and on_attempt:
            record(child["modelAttempts"][-1])
    state["status"] = "complete"
    return _merged_decision(state["batches"], edits, len(rows)), edits
