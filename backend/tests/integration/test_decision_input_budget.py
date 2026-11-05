"""First requests, not just repairs, must fit the serving tokenizer's budget."""

# ruff: noqa: F811

import copy
import hashlib
import json
from unittest.mock import patch

import pytest

from apps.agent.decision_budget import MAX_LEVEL, project_payload, visible_payload
from apps.agent.demo_decisions import decide, decision_payload
from apps.agent.geology_issue_groups import group_summaries
from apps.agent.policy import default_policy
from tests.integration.test_demo_decision_retry import (  # noqa: F401
    ordinary_stage,
    responses,
    retry_model,
)
from tests.integration.test_demo_edit_context import model_response


def expand(value, definitions):
    if isinstance(value, dict):
        if set(value) == {"$ref"}:
            return expand(definitions[value["$ref"]], definitions)
        return {
            key: expand(item, definitions)
            for key, item in value.items()
            if key not in {"contextDefinitions", "contextProjectionNote"}
        }
    if isinstance(value, list):
        return [expand(item, definitions) for item in value]
    return value


@pytest.mark.parametrize("level", [2, 3, 4])
def test_complete_batch_keeps_members_totals_and_quality_without_map_headers(level):
    members = [{"issue_id": f"i-{index}", "area": index / 10} for index in range(70)]
    statistics = [{"rule_id": f"L-{index}", "count": index} for index in range(20)]
    payload = {
        "allowedAction": "geology-multi-apply",
        "modelBatch": {"completeMembers": True, "memberCount": len(members)},
        "knowledge": [],
        "actualResults": [
            {
                "key": "issues",
                "outputId": 1,
                "rows": [],
                "groups": [{"group_id": "g", "rule_id": "L-1", "samples": members}],
                "metadata": {"qualityCheck": {"status": "passed"}, "fields": ["area"]},
            },
            {"key": "statistics", "outputId": 2, "rows": statistics, "scope": "all"},
            {"key": "alteration_quality", "outputId": 3, "rows": [{"bad_pixels": 7}]},
            {
                "key": "mineral_hits",
                "kind": "raster",
                "outputId": 4,
                "checksum": "a" * 64,
                "metadata": {"width": 10000, "warnings": ["no CRS"]},
                "rows": [],
            },
            {"key": "alteration_summary", "outputId": 5, "rows": [{"unit": "unseen"}]},
        ],
        "editTask": {"issueRuleKnowledge": [{"ruleId": "L-1"}, {"ruleId": "L-2"}]},
        "availableEvidence": [
            {"kind": "output", "id": str(index)} for index in range(1, 6)
        ],
    }
    original = copy.deepcopy(payload)
    result = visible_payload(payload, level)
    assert result["actualResults"][0]["groups"][0]["samples"] == members
    assert result["actualResults"][0]["metadata"] == {
        "qualityCheck": {"status": "passed"}
    }
    assert result["actualResults"][1]["rows"] == statistics
    assert result["actualResults"][1]["scope"] == "all"
    assert result["actualResults"][2]["rows"] == [{"bad_pixels": 7}]
    assert len(result["actualResults"]) == 3
    assert result["batchEvidenceProjection"]["referenceOnlyOutputIds"] == [4, 5]
    assert result["batchEvidenceProjection"]["referenceArtifactQuality"][0] == {
        "outputId": 4,
        "quality": {"warnings": ["no CRS"]},
    }
    assert result["availableEvidence"] == payload["availableEvidence"][:3]
    assert result["editTask"]["issueRuleKnowledge"] == [{"ruleId": "L-1"}]
    if level == 2:
        assert (
            result["batchEvidenceProjection"]["sourceSha256"]
            == hashlib.sha256(
                json.dumps(
                    original["actualResults"], ensure_ascii=False, separators=(",", ":")
                ).encode()
            ).hexdigest()
        )
    else:
        assert "sourceSha256" not in result["batchEvidenceProjection"]
        assert "原始阶段审计" in result["batchEvidenceProjection"]["auditScope"]
    assert payload == original


@pytest.mark.parametrize(
    "thinking,effort", [(False, "low"), (True, "medium"), (True, "xhigh")]
)
def test_raster_protocol_caps_first_request_and_generation(
    retry_model, thinking, effort
):
    workflow, stage, payload, _ = large_payload()
    workflow.workflow_type = "geology_multi_element_reasoning"
    workflow.plan["algorithms"] = {
        "geology-multi-check": {
            "manifest": {"outputs": [{"key": "alteration_summary"}]}
        }
    }
    requests = []
    answer = model_response(stage["identifier"], [])
    policy = {
        **default_policy(),
        "maxContextTokens": 49152,
        "maxOutputTokens": 8000,
        "_thinking": thinking,
        "reasoningEffort": effort,
    }
    counted = []

    def tokenizer(model, messages, enabled, selected):
        counted.append((enabled, selected))
        return sum(len(item["content"].encode("utf-8")) for item in messages) // 4 + 64

    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.decision_payload", return_value=payload),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=65536),
        patch("apps.agent.context.count_tokens", side_effect=tokenizer),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            side_effect=responses([answer], requests),
        ) as generation,
        patch(
            "apps.agent.demo_decisions._validate_response",
            return_value=(answer["decision"], []),
        ),
    ):
        decide(workflow, None, policy, stage, [], lambda: None)
    assert len(requests) == 1
    attempt = stage["modelAttempts"][0]
    assert attempt["inputTokens"] <= attempt["inputLimit"] == 15000
    assert attempt["outputLimit"] == 2000
    assert set(counted) == {(thinking, effort)}
    assert generation.call_args.kwargs["thinking"] is thinking
    assert generation.call_args.kwargs["reasoning_effort"] == effort
    assert attempt["thinkingEnabled"] is thinking
    assert attempt["reasoningEffort"] == effort


def large_payload():
    workflow, stage, _ = ordinary_stage()
    rows = []
    workflow.evidence = []
    rules = []
    for index in range(20):
        rule_id = f"L-{index + 1:02d}"
        rule = {
            "rule_id": rule_id,
            "rule_version": "trial-3",
            "knowledge_id": 200 + index,
            "knowledge_revision": 3,
        }
        rules.append(rule)
        workflow.evidence.append(
            {
                "id": 200 + index,
                "revision": 3,
                "title": rule_id + "地质适用条件",
                "statement": f"{rule_id}的实测面积、置信度及适用条件。" * 150,
                "explanation": f"知识{index}地质解释与完整原文。" * 200,
                "conditions": ["仅限本研究区，必须实测面积与规则阈值相符"],
                "exceptions": ["例外必须保留，边界不明时人工核查"],
                "trialBinding": {"ruleId": rule_id, "ruleVersion": "trial-3"},
                "ruleConfig": {
                    "rule": {"area_m2": {"lt": 500}},
                    "parameters": {"min_confidence": 0.8},
                },
            }
        )
    for index in range(5400):
        group = index % 45
        rows.append(
            {
                "issue_id": f"issue-{index}",
                "feature_id": f"object-{index}",
                "element": "lithology",
                "rule_id": rules[group % 20]["rule_id"],
                "rule_version": "trial-3",
                "target_code": f"unit-{group}",
                "suggested_action": "set_code",
                "status": "suggested",
                "snapshot_hash": "a" * 64,
                "reason": f"对象{index}按实测范围评估",
                "conditions": "面积、置信度、地层边界须共同满足",
                "exceptions": "接触关系不明则待裁定",
                "measurements_json": json.dumps(
                    {
                        "area_m2": index + 0.5,
                        "confidence": 0.9,
                        "unrelated_trace": f"对象{index}的历史处理记录" * 60,
                    },
                    ensure_ascii=False,
                ),
            }
        )
    groups = group_summaries(rows)
    context = [{"role": "rules", "resourceId": 668, "title": "20条规则", "rows": rules}]
    payload = decision_payload(workflow, stage, context, [])
    payload["actualResults"] = [{"key": "issues", "outputId": 17, "groups": groups}]
    payload["previousDecisions"] = [
        {"judgement": "历史结论" * 300, "findings": ["旧阶段详细分析" * 300]}
    ]
    return workflow, stage, payload, rows


@pytest.mark.parametrize("level", range(1, MAX_LEVEL + 1))
def test_every_group_preserves_rule_count_ranges_and_required_knowledge(level):
    _, _, payload, rows = large_payload()
    original = copy.deepcopy(payload)
    compressed = project_payload(payload, level)
    restored = expand(compressed, compressed["contextDefinitions"])
    groups = restored["actualResults"][0]["groups"]
    assert len(rows) == 5400 and len(groups) == (24 if level == 4 else 45)
    if level == 4:
        summary = next(
            item
            for item in restored["evidenceProjection"]
            if item["path"].endswith(".groups")
        )
        assert (
            summary["inputCount"] == 45 and summary["completeInputObjectCount"] == 5400
        )
        assert summary["coverage"] == "shown_items_only"
    else:
        assert sum(group["count"] for group in groups) == 5400
    originals = {
        group["group_id"]: group for group in payload["actualResults"][0]["groups"]
    }
    for group in groups:
        original_group = originals[group["group_id"]]
        for key in (
            "rule_id",
            "rule_version",
            "count",
            "measurementRanges",
            "conditions",
            "exceptions",
        ):
            assert group[key] == original_group[key]
        assert group["requiredKnowledgeRefs"] == [
            {"id": 199 + int(group["rule_id"][2:]), "revision": 3}
        ]
        if level >= 2:
            assert len(group["samples"]) <= 1
            for sample in group["samples"]:
                assert set(json.loads(sample["measurements_json"])) == {
                    "area_m2",
                    "confidence",
                }
    if level >= 3:
        assert "findings" not in restored["previousDecisions"][0]
        for entry, source in zip(
            restored["knowledge"], payload["knowledge"], strict=True
        ):
            for key in (
                "id",
                "revision",
                "conditions",
                "exceptions",
                "ruleConfig",
                "trialBinding",
            ):
                assert entry[key] == source[key]
            assert len(entry["explanation"]) < len(source["explanation"])
    assert payload == original


@pytest.mark.parametrize(
    "phase", ["check", "apply", "recheck", "relations", "prospect", "final_analysis"]
)
def test_first_request_uses_actual_tokenizer_gate_for_every_stage(phase, retry_model):
    workflow, stage, payload, _ = large_payload()
    stage["name"] = phase
    policy = {**default_policy(), "maxContextTokens": 49152, "maxContextBytes": 384000}
    requests, measured = [], []
    answer = model_response(stage["identifier"], [])

    def tokenizer(model, messages, thinking, effort):
        tokens = sum(len(item["content"].encode("utf-8")) for item in messages) + 64
        measured.append(tokens)
        return tokens

    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.decision_payload", return_value=payload),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=65536),
        patch("apps.agent.context.count_tokens", side_effect=tokenizer),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            side_effect=responses([answer], requests),
        ),
        patch(
            "apps.agent.demo_decisions._validate_response",
            return_value=(answer["decision"], []),
        ),
    ):
        outcome = decide(workflow, None, policy, stage, [], lambda: None)
    assert outcome[0]["nextAction"] == stage["identifier"]
    assert len(requests) == 1 and measured[0] > 49152
    attempt = stage["modelAttempts"][0]
    assert attempt["inputTokens"] == measured[-1] <= attempt["inputLimit"] == 49152
    assert attempt["contentBytes"] <= policy["maxContextBytes"]
    assert attempt["budgetLevel"] > 0 and not attempt["truncated"]
    assert stage["modelRequestPayload"] == payload
    expected = json.dumps(requests[0], ensure_ascii=False).encode("utf-8")
    assert attempt["requestSha256"] == hashlib.sha256(expected).hexdigest()
    projected = json.loads(requests[0][1]["content"])
    groups = expand(projected, projected["contextDefinitions"])["actualResults"][0][
        "groups"
    ]
    assert len(groups) == 45 and sum(group["count"] for group in groups) == 5400
    print(
        f"{phase}: first request fixture-byte-tokenizer={attempt['inputTokens']}, budget={attempt['inputLimit']}, level={attempt['budgetLevel']}"
    )


@pytest.mark.parametrize("gate", ["tokens", "bytes"])
def test_actual_apply_assembly_and_response_validation_fit_first_request(
    gate, retry_model
):
    workflow, stage, source, rows = large_payload()
    rows = rows[:90]
    workflow.workflow_type = "geology_multi_element_reasoning"
    stage.update(name="apply", identifier="geology-multi-apply")
    workflow.plan["stages"] = [
        {"name": "check", "identifier": "geology-multi-check", "taskId": "check-task"},
        stage,
    ]
    workflow.plan["trialRuleBindings"] = [
        {"id": entry["id"], "revision": entry["revision"], **entry["trialBinding"]}
        for entry in workflow.evidence
    ]
    results = [
        {"key": "issues", "outputId": 17, "taskId": "check-task", "rows": rows},
        {
            "key": "statistics",
            "outputId": 18,
            "taskId": "check-task",
            "rows": [{"objects": 90, "groups": 45}],
        },
    ]
    answer = model_response(stage["identifier"], [])
    answer["decision"]["evidenceRefs"] = [
        {"kind": "output", "id": "18"},
        {"kind": "knowledge", "id": "200", "revision": 3},
    ]
    requests = []
    policy = {**default_policy(), "maxContextTokens": 49152}
    if gate == "bytes":
        policy["maxContextBytes"] = 49152

    def tokenizer(model, messages, thinking, effort):
        if gate == "bytes":
            return 800
        return sum(len(item["content"].encode("utf-8")) for item in messages) + 64

    def stream(model, messages, output, guard, **options):
        requests.append(copy.deepcopy(messages))
        sent = json.loads(messages[1]["content"])
        visible = expand(sent, sent.get("contextDefinitions", {}))
        value = copy.deepcopy(answer)
        entry = visible["knowledge"][0]
        value["decision"]["evidenceRefs"][1] = {
            "kind": "knowledge",
            "id": str(entry["id"]),
            "revision": entry["revision"],
        }
        return iter([json.dumps(value, ensure_ascii=False)])

    with (
        patch(
            "apps.agent.demo_decisions.resource_context",
            return_value=source["inputRoles"],
        ),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=65536),
        patch("apps.agent.context.count_tokens", side_effect=tokenizer),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            side_effect=stream,
        ),
    ):
        decision, edits = decide(workflow, None, policy, stage, results, lambda: None)
    assert decision["nextAction"] == stage["identifier"] and edits == []
    assert len(requests) > 1
    assert stage["modelBatches"]["coveredMemberCount"] == 90
    for batch in stage["modelBatches"]["batches"]:
        attempt = batch["stage"]["modelAttempts"][0]
        assert attempt["inputTokens"] <= attempt["inputLimit"] == 15000
        assert attempt["outputLimit"] == 2000
        assert attempt["contentBytes"] <= policy["maxContextBytes"]
        request = requests[attempt["batchIndex"] - 1]
        sent = json.loads(request[1]["content"])
        restored = expand(sent, sent.get("contextDefinitions", {}))
        groups = restored["actualResults"][0]["groups"]
        assert all(len(group["samples"]) == group["count"] for group in groups)
        assert all(group["measurementRanges"] for group in groups)


def test_exact_references_expand_before_summarizing_knowledge():
    _, _, payload, _ = large_payload()
    payload["knowledge"][1]["conditions"] = {"sameAs": "knowledge[0].conditions"}
    compact = project_payload(payload, 3)
    restored = expand(compact, compact["contextDefinitions"])
    assert (
        restored["knowledge"][1]["conditions"] == payload["knowledge"][0]["conditions"]
    )
