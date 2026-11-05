"""Sequential, resumable model review of complete, snapshot-bound member scopes."""

import copy
import hashlib
import json
import re
from collections import Counter

from apps.compute.packages import ComputeError
from .config import registry
from .decision_budget import BudgetReviewRequired, _expand_knowledge
from .geology_issue_groups import group_summaries

# Configuration: request size adapts downward through the real tokenizer gate.
MAX_BATCH_ROWS = 128
MAX_BATCH_GROUPS = 8
MODEL_GROUP_FIELDS = (
    "element",
    "rule_id",
    "rule_version",
    "suggested_action",
    "status",
    "snapshot_hash",
    "conditions",
    "exceptions",
    "knowledge_id",
    "knowledge_revision",
)
SOURCE_POLICY_KEYS = (
    "maxContextTokens",
    "maxContextBytes",
    "maxOutputTokens",
    "reasoningEffort",
    "_thinking",
    "temperature",
    "topP",
)


class BatchProgressPending(Exception):
    """A complete batch is durable; remaining batches belong to the next tick."""


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
    members = [
        (result, index, row)
        for result in results
        if result["key"] == "issues" and result.get("taskId") == check.get("taskId")
        for index, row in enumerate(result.get("rows", []))
    ]
    # Keep compatible members adjacent before applying the group/row caps.
    # The original output row index remains the source locator and audit key.
    return sorted(
        members,
        key=lambda item: (_model_group_key(item[2]), str(item[0]["outputId"]), item[1]),
    )


def _model_group_key(row):
    raster = row.get("element") == "alteration" and str(
        row.get("feature_id", "")
    ).startswith("AG-")
    return tuple(str(row.get(name, "")) for name in MODEL_GROUP_FIELDS) + (
        "raster_unit" if raster else "feature",
    )


def model_issue_groups(rows):
    """Pack complete members sharing a rule; keep individual target/evidence values."""
    grouped = {}
    for row in rows:
        grouped.setdefault(_model_group_key(row), []).append(row)
    return [
        (
            ("AGB-" if key[-1] == "raster_unit" else "MGB-") + signature(key)[:24],
            members,
        )
        for key, members in sorted(grouped.items())
    ]


def model_group_summaries(rows):
    summaries = []
    for identity, members in model_issue_groups(rows):
        parts = group_summaries(members)
        value = {**parts[0], "group_id": identity, "count": len(members)}
        ranges = {}
        for part in parts:
            for name, bounds in part["measurementRanges"].items():
                current = ranges.setdefault(name, list(bounds))
                current[:] = [min(current[0], bounds[0]), max(current[1], bounds[1])]
        value["measurementRanges"] = ranges
        value["modelGroupKind"] = (
            "complete_raster_units"
            if identity.startswith("AGB-")
            else "complete_vector_members"
        )
        targets = Counter(row.get("target_code", "") for row in members)
        if len(targets) > 1:
            value.update(
                target_code=None,
                targetCodeMode="per_member",
                targetCodeDistribution=dict(sorted(targets.items())),
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


def _member_projection(row, knowledge):
    member = {key: cell for key, cell in row.items() if key != "geometry_json"}
    if row.get("element") != "alteration" or not str(
        row.get("feature_id", "")
    ).startswith("AG-"):
        return member
    measured = json.loads(row.get("measurements_json") or "{}")
    if measured.get("raster_protocol") != "alteration-pixels-v1":
        return member
    predicates = [row.get("conditions"), row.get("exceptions")]
    predicates.extend(
        {key: entry.get(key) for key in ("conditions", "exceptions", "ruleConfig")}
        for entry in knowledge
        if not entry.get("trialBinding", {}).get("ruleId")
        or entry["trialBinding"]["ruleId"] == row.get("rule_id")
    )
    if re.search(
        r"bbox|coordinates?|包围框|边界框|坐标|representatives[^\n]*(?:location|longitude|latitude|\.(?:x|y|lon|lat)\b)",
        json.dumps(predicates, ensure_ascii=False),
        re.I,
    ):
        return member
    omitted = []
    if "bbox" in measured:
        measured.pop("bbox")
        omitted.append("measurements_json.bbox")
    representatives = measured.get("representatives")
    for representative in representatives if isinstance(representatives, list) else []:
        if isinstance(representative, dict) and "bbox" in representative:
            representative.pop("bbox")
            path = "measurements_json.representatives[].bbox"
            if path not in omitted:
                omitted.append(path)
    if omitted:
        member.update(
            measurements_json=json.dumps(
                measured, ensure_ascii=False, separators=(",", ":")
            ),
            omittedGeometryPaths=omitted,
            geometryStoredInOriginal=True,
        )
    return member


def _measurement_columns(group, members):
    measured = [json.loads(row.get("measurements_json") or "{}") for row in members]
    aliases = {}
    if all(
        "group_id" in values
        and "feature_id" in row
        and signature(values["group_id"]) == signature(row["feature_id"])
        for row, values in zip(members, measured)
    ):
        aliases["group_id"] = "feature_id"
    first_signatures = {key: signature(value) for key, value in measured[0].items()}
    common = {
        key: value
        for key, value in measured[0].items()
        if key not in aliases
        and all(
            key in values and signature(values[key]) == first_signatures[key]
            for values in measured
        )
    }
    columns = sorted(
        {key for values in measured for key in values} - set(common) - set(aliases)
    )
    group.update(
        measurementCommon=common,
        measurementColumns=columns,
        measurementAliases=aliases,
    )
    group["memberCommon"].pop("measurements_json", None)
    for sample, values in zip(group["samples"], measured):
        sample.pop("measurements_json", None)
        sample["measurements"] = [values.get(key) for key in columns]
        absent = [index for index, key in enumerate(columns) if key not in values]
        if absent:
            sample["measurementAbsentColumns"] = absent


def batch_payload(payload, results, scope, batch_index):
    """Every member is visible; a group refers only to this request's scope."""
    value = _expand_knowledge(payload)
    rules = {row["rule_id"] for _, _, row in scope}
    original_knowledge = value["knowledge"]
    bound = [
        entry
        for entry in original_knowledge
        if entry.get("trialBinding", {}).get("ruleId") in rules
    ]
    background = [
        entry
        for entry in original_knowledge
        if not entry.get("trialBinding", {}).get("ruleId")
    ]
    if bound:
        value["knowledge"] = bound
        if background:
            value["batchKnowledgeScope"] = {
                "reviewedRuleIds": sorted(rules),
                "sourceSha256": signature(original_knowledge),
                "deferredBackground": [
                    {
                        key: entry[key]
                        for key in ("id", "revision", "title")
                        if key in entry
                    }
                    for entry in background
                ],
                "note": "本批只审阅绑定规则的完整条件、例外与配置；背景知识正文留在原审计，"
                "尚未在本批审阅，不能引用其内容。需要这些背景才能裁定时须request_review。",
            }
    else:
        value["knowledge"] = background or original_knowledge
    selected = {}
    sources = {}
    for result, index, row in scope:
        member = _member_projection(row, value["knowledge"])
        sources[str(result["outputId"])] = {
            "outputId": result["outputId"],
            "checksum": result.get("checksum"),
            "geometryStoredInOriginal": True,
        }
        member["sourceRowIndex"] = index
        selected.setdefault(str(result["outputId"]), []).append(member)
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
            _measurement_columns(group, group_members)
            group["memberCoverage"] = "complete_batch_members"
        result.update(rows=[], groups=groups, scope="complete_batch_members")
    for role in value["inputRoles"]:
        if role.get("role") == "rules":
            source_rows = role.get("rows", [])
            rows = [row for row in source_rows if row.get("rule_id") in rules]
            original_reading = copy.deepcopy(role.get("readingScope"))
            role.update(
                rows=rows,
                sourceRowCount=role.get("rowCount", len(source_rows)),
                sourceScope=role.get("scope"),
                rowCount=len(rows),
                scope="batch_rule_bindings",
                readingScope={
                    "scope": "batch_rule_bindings",
                    "sourceRowsSha256": signature(source_rows),
                    "originalReading": original_reading,
                    "note": "原读取范围记录于originalReading及完整输入审计；这里只列本批绑定规则，不是完整原表。",
                },
            )
    value["modelBatch"] = {
        "index": batch_index,
        "completeMembers": True,
        "memberCount": len(scope),
        "scopeSha256": scope_signature(scope),
        "instruction": "本批groups的samples包含全部本批成员。group_id仅在本批范围展开；"
        "每个成员继承该组memberCommon的完全相同原值；memberSource与sourceRowIndex定位原始行。"
        "原measurements_json由measurementCommon与measurementColumns对应的成员measurements数组合并还原；"
        "measurementAbsentColumns列出原本缺少的列索引（从0开始），不能把缺失当null。"
        "measurementAliases将测量键精确指向该成员的原字段，例如group_id=feature_id；"
        "这些是无损编码，所有未省几何的原JSON键、值、类型和嵌套结构完整保留。"
        "分组只是展示打包；targetCodeMode为per_member时目标按每个成员的target_code，"
        "矿物、岩性背景、边界与测量均按各成员原值核查，不能将一个成员的证据用于其他成员。"
        "omittedGeometryPaths所列包围框留在原输出，本批未审阅这些坐标几何；"
        "不能声称已做原始几何或空间复核。"
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
            "batchProtocol": "complete_rule_members_measurement_columns_v5",
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


def _new_child_stage(stage):
    return {
        key: copy.deepcopy(stage[key])
        for key in ("name", "identifier", "bindings", "parameters")
        if key in stage
    }


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
            child = _new_child_stage(stage)
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
    *,
    batch_limit=None,
    **callbacks,
):
    if batch_limit is not None and (type(batch_limit) is not int or batch_limit < 1):
        raise ValueError("每次分批推进上限必须是正整数")
    completed_this_tick = 0
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
    offset, edits, chosen = 0, [], {}
    targets = {
        row["issue_id"]: (row["element"], row["feature_id"]) for _, _, row in rows
    }
    selected_sources = {(str(result["outputId"]), index) for result, index, _ in rows}
    original_rows = [
        row
        for result in results
        if result["key"] == "issues"
        for index, row in enumerate(result.get("rows", []))
        if (str(result["outputId"]), index) in selected_sources
    ]
    priority = {row["issue_id"]: index for index, row in enumerate(original_rows)}

    def merge(proposed):
        for edit in proposed:
            target = targets[edit["issue_id"]]
            previous = chosen.get(target)
            if (
                previous is None
                or priority[edit["issue_id"]] < priority[previous["issue_id"]]
            ):
                chosen[target] = edit
        edits[:] = sorted(chosen.values(), key=lambda edit: priority[edit["issue_id"]])

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
        from .demo_decisions import _response_text

        for attempt in batch["stage"].get("modelAttempts", []):
            artifact = attempt.get("responseArtifact")
            if (
                not isinstance(artifact, dict)
                or not isinstance(artifact.get("content"), str)
                or artifact.get("truncated") is not False
                or artifact.get("sizeBytes") != len(artifact["content"].encode("utf-8"))
                or _response_text(artifact["content"]) != attempt.get("response")
            ):
                raise ComputeError("已完成批次的原始响应审计发生变化，已停止恢复")
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
            **(
                {"_expected_request_sha": preflight["batches"][index]["requestSha256"]}
                if preflight
                else {}
            ),
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
                "stage": _new_child_stage(stage),
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
                **(
                    {
                        "_expected_request_sha": preflight["batches"][index][
                            "requestSha256"
                        ]
                    }
                    if preflight
                    else {}
                ),
                **callbacks,
            )
        except BudgetReviewRequired as exc:
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
                **copy.deepcopy(child.get("contextBudgetReview", {})),
                "reason": str(exc),
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
        completed_this_tick += 1
        if (
            offset < len(rows)
            and batch_limit is not None
            and completed_this_tick >= batch_limit
        ):
            state["status"] = "pending"
            raise BatchProgressPending()
    state["status"] = "complete"
    return _merged_decision(state["batches"], edits, len(rows)), edits
