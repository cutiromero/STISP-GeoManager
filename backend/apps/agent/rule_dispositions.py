"""Build bounded dispositions from complete, measured and knowledge-bound issues."""

from collections import Counter, defaultdict

from apps.compute.packages import ComputeError
from .geology_multi_review import assess_edits, issue_rows

POLICY = "rule_geology_v2"
ACTIONS = {"set_code", "merge", "reclassify", "exclude", "downweight"}


def report_payload(payload, workflow):
    """A report reads real totals and evidence; it does not review edits again."""
    payload["knowledge"] = [
        {
            key: entry[key]
            for key in (
                "id",
                "revision",
                "title",
                "statement",
                "conditions",
                "exceptions",
                "sources",
                "trialBinding",
            )
            if key in entry and (key != "statement" or not entry.get("trialBinding"))
        }
        for entry in workflow.evidence
    ]
    projected = []
    for result in payload["actualResults"]:
        if result["key"] not in {
            "issues",
            "statistics",
            "changes",
            "evidence",
            "alteration_quality",
        }:
            continue
        value = {key: item for key, item in result.items() if key != "metadata"}
        if result["kind"] not in {"table", "archive"}:
            value = {
                key: value[key]
                for key in ("outputId", "taskId", "key", "kind", "checksum", "rowCount")
                if key in value
            }
            value.update(scope="reference_only", rows=[])
        projected.append(value)
    payload["actualResults"] = projected
    stage_tasks = {
        stage["name"]: stage.get("taskId") for stage in workflow.plan["stages"]
    }
    issue_counts = {
        item.get("taskId"): item.get("rowCount")
        for item in projected
        if item["key"] == "issues"
    }
    changes = [
        item
        for item in projected
        if item["key"] == "changes" and item.get("taskId") == stage_tasks.get("apply")
    ]
    payload["verifiedReportFacts"] = {
        "initialIssueCount": issue_counts.get(stage_tasks.get("check")),
        "recheckRemainingIssueCount": issue_counts.get(stage_tasks.get("recheck")),
        "executedDispositionCount": changes[0].get("rowCount") if changes else None,
        "executedActions": dict(
            Counter(
                {
                    action: sum(
                        int(row.get("count", 0))
                        for item in changes
                        for row in item.get("rows", [])
                        if row.get("action") == action
                    )
                    for action in sorted(ACTIONS)
                }
            )
        ),
        "note": "问题记录、执行处置、复查剩余和保留项是不同口径；降权不表示该问题记录消失。",
    }
    review = payload.get("modificationReview")
    if review:
        groups = {}
        for item in review.get("groups", []):
            key = (item.get("element"), item.get("ruleId"), item.get("action"))
            group = groups.setdefault(
                key,
                {
                    "element": key[0],
                    "ruleId": key[1],
                    "action": key[2],
                    "count": 0,
                    "approvedCount": 0,
                },
            )
            group["count"] += item["count"]
            group["approvedCount"] += item["approvedCount"]
        payload["modificationReview"] = {
            **{
                key: review[key]
                for key in (
                    "proposalHash",
                    "approvedCount",
                    "suggestionCount",
                    "approvalScopeDigest",
                    "sourceOutputs",
                )
                if key in review
            },
            "scope": "complete_rule_action_counts",
            "groups": list(groups.values()),
        }
    report_outputs = {
        str(item["outputId"])
        for item in projected
        if item["key"] in {"statistics", "changes", "evidence", "alteration_quality"}
    }
    payload["availableEvidence"] = [
        item
        for item in payload["availableEvidence"]
        if item["kind"] == "knowledge"
        or item["kind"] == "output"
        and str(item["id"]) in report_outputs
    ]
    payload["reportScope"] = (
        "实际完整统计、处置汇总及远景依据；栅格与矢量明细保留在已完成任务和审计中，本次不重新请求修改。"
    )
    return payload


def build_rule_proposal(workflow):
    check = next(s for s in workflow.plan["stages"] if s["name"] == "check")
    results = check.get("results", [])
    issues = [item for item in results if item.get("key") == "issues"]
    if len(issues) != 1 or (
        issues[0].get("taskId") != check.get("taskId")
        or issues[0].get("scope") != "all"
        or issues[0].get("rowCount") != len(issues[0].get("rows", []))
    ):
        raise ComputeError("自动规则处置需要本次完整实际问题清单", 409)
    rows = issue_rows(results)
    if len({row["issue_id"] for row in rows}) != len(rows):
        raise ComputeError("实际问题清单包含重复编号", 409)
    entries = {
        (
            e.get("trialBinding", {}).get("ruleId"),
            e.get("trialBinding", {}).get("ruleVersion"),
        ): e
        for e in workflow.evidence
    }
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["element"], row["feature_id"])].append(row)
    held, edits, bindings = Counter(), [], {}
    for members in grouped.values():
        if any(row.get("status") != "suggested" for row in members):
            held["review_or_exception"] += len(members)
            continue
        signatures = {
            (row.get("suggested_action"), row.get("target_code", "")) for row in members
        }
        if len(signatures) != 1:
            held["conflicting_actions"] += len(members)
            continue
        row = members[0]
        entry = entries.get((row["rule_id"], row["rule_version"]))
        if (
            not entry
            or str(entry["id"]) != str(row.get("knowledge_id"))
            or str(entry["revision"]) != str(row.get("knowledge_revision"))
        ):
            held["unbound_knowledge"] += len(members)
            continue
        action = row.get("suggested_action")
        if action not in ACTIONS:
            held["unsupported_action"] += len(members)
            continue
        # The operator owns rule predicates and spatial measurements. The platform
        # revalidates identities, allowed actions and knowledge before execution.
        edits.append(
            {
                "issue_id": row["issue_id"],
                "action": action,
                "target_code": row.get("target_code", "")
                if action in {"set_code", "merge", "reclassify"}
                else "",
                "weight": 0
                if action == "exclude"
                else 0.5
                if action == "downweight"
                else 1,
                "reason": row["reason"],
            }
        )
        bindings[entry["id"]] = entry
    summary = {
        "issueCount": len(rows),
        "eligibleCount": len(edits),
        "retainedIssueCount": len(rows) - len(edits),
        "retainedReasons": dict(held),
        "actions": dict(Counter(edit["action"] for edit in edits)),
        "sourceTaskId": check["taskId"],
        "policy": POLICY,
    }
    text = (
        f"已核验{len(rows)}条实际问题，形成{len(edits)}项规则处置；其余问题保留供复核"
    )
    refs = [
        {
            "kind": "knowledge",
            "id": str(e["id"]),
            "revision": e["revision"],
            "title": e["title"],
        }
        for e in bindings.values()
    ] + [
        {"kind": "output", "id": str(item["outputId"]), "title": item.get("key", "")}
        for item in results
        if item.get("key") in {"issues", "statistics"}
    ]
    decision = {
        "problem": "依据实际检查与冻结规则生成处置",
        "findings": [text],
        "judgement": text,
        "uncertainties": ["待裁定、规则例外、冲突和缺少知识依据的对象保持原样"]
        if held
        else [],
        "nextAction": "geology-multi-apply",
        "algorithmReason": "使用算子实际测量及本次绑定知识，保留逐对象记录；不以模型重复判定替代测量",
        "evidenceRefs": refs,
        "resultSummary": text,
        "modelMode": "rules",
        "modelName": "实际测量与规则核验",
    }
    accepted, assessment = assess_edits(
        edits, results, workflow=workflow, decision=decision
    )
    if assessment["errors"]:
        raise ComputeError("规则处置未通过实际证据校验，已保留原始资料", 409)
    return (
        decision,
        [
            {
                key: row[key]
                for key in ("issue_id", "action", "target_code", "weight", "reason")
            }
            for row in accepted
        ],
        summary,
    )


def automatic_authorized(workflow, user, policy):
    from .input_execution import input_execution_authorized

    return (
        workflow.plan.get("executionPolicy") == POLICY
        and workflow.plan.get("inputExecutionAuthorization", {}).get(
            "applyRuleSuggestions"
        )
        is True
        and input_execution_authorized(workflow, user, policy)
    )


def authorize_rule_execution(workflow, user, policy, stage):
    """Record execution under prior explicit scope, without claiming a new click."""
    from .geology_multi_review import execution_hash, selected_edits
    from .workflow import step

    if not automatic_authorized(workflow, user, policy):
        return False
    review = workflow.plan["modificationReview"]
    selected = [
        s["id"]
        for s in review["suggestions"]
        if s["status"] == "suggested" and not s.get("candidateAction")
    ]
    proof = {
        "mode": "rule_authorized",
        "proposalHash": review["proposalHash"],
        "selectedSuggestionIds": selected,
        "executionHash": execution_hash(workflow, stage),
        "inputAuthorization": workflow.plan["inputExecutionAuthorization"],
    }
    stage.update(
        modificationsApproval=proof,
        approvedEdits=selected_edits(stage["proposedEdits"], review, selected),
        status="pending",
    )
    review["approvedSuggestionIds"] = selected
    review["unapprovedSuggestionIds"] = [
        s["id"] for s in review["suggestions"] if s["id"] not in set(selected)
    ]
    workflow.plan.update(phase="decide", reviewOutputs=[])
    workflow.status = "queued"
    workflow.detail = f"按本次授权执行{len(selected)}项规则处置；待裁定与例外保持原样"
    step(workflow, "automatic_dispositions", action=proof, message=workflow.detail)
    return True
