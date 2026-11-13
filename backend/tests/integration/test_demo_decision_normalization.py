"""Presentation normalization never relaxes action or evidence authorization."""

import json
from unittest.mock import patch

import pytest

from apps.agent.decision_audit import MAX_RESPONSE_BYTES, response_artifact
from apps.agent.demo_decisions import validate_decision
from apps.agent.provider import ModelError
from apps.compute.packages import ComputeError
from tests.integration.test_demo_decision_retry import (
    ordinary_stage,
    retry_model,  # noqa: F401
    run,
)
from tests.integration.test_demo_edit_context import model_response

pytestmark = pytest.mark.usefixtures("retry_model")


def validate(changes=None, refs=None):
    value = model_response("ecology-priority", [])["decision"]
    value.update(changes or {})
    refs = refs or [{"kind": "output", "id": "101", "title": "实际统计"}]
    value["evidenceRefs"] = (changes or {}).get("evidenceRefs", refs)
    return validate_decision(value, refs, "ecology-priority", require_output=True)


def test_findings_merge_tail_and_preserve_original_audit():
    workflow, stage, results = ordinary_stage()
    answer = model_response("ecology-priority", [])
    findings = [f"发现{index}" for index in range(35)]
    answer["decision"]["findings"] = findings
    (decision, _), requests = run([answer], workflow, stage, results)
    assert len(requests) == 1
    assert decision["findings"][:11] == findings[:11]
    assert decision["findings"][11].startswith("另有 24 项：发现11")
    assert "发现34" in decision["findings"][11]
    artifact = stage["modelAttempts"][0]["responseArtifact"]
    assert json.loads(artifact["content"])["decision"]["findings"] == findings


def test_objects_empty_items_duplicates_and_scalar_text():
    decision = validate(
        {
            "findings": [
                None,
                " ",
                {},
                {"title": "岩性", "description": "需复核"},
                "岩性：需复核",
            ],
            "uncertainties": {"标题": "边界", "说明": "未确认"},
        }
    )
    assert decision["findings"] == ["岩性：需复核"]
    assert decision["uncertainties"] == ["边界：未确认"]
    assert validate({"findings": "单条发现"})["findings"] == ["单条发现"]


def test_long_narrative_and_merged_tail_are_marked_and_bounded():
    long = "长" * 5000
    value = validate(
        {
            "findings": [long, *[str(index) + long for index in range(15)]],
            "uncertainties": [long],
            "problem": long,
            "judgement": long,
            "algorithmReason": long,
            "resultSummary": long,
        }
    )
    for key in ("problem", "judgement", "algorithmReason"):
        assert len(value[key]) == 2000 and value[key].endswith("（已截断）")
    assert len(value["resultSummary"]) == 4000
    for key in ("findings", "uncertainties"):
        assert len(value[key]) <= 12
        assert all(
            len(item) <= 2000 and item.endswith("（已截断）") for item in value[key]
        )


def test_references_deduplicate_preserve_authorized_tail_and_check_entire_list():
    refs = [{"kind": "output", "id": str(index)} for index in range(40)]
    value = validate({"evidenceRefs": [refs[0]] * 40 + refs}, refs)
    assert value["evidenceRefs"] == refs
    with pytest.raises(ComputeError, match="第81项.*并非本次授权"):
        validate(
            {
                "evidenceRefs": [refs[0]] * 40
                + refs
                + [{"kind": "output", "id": "fake"}]
            },
            refs,
        )
    with pytest.raises(ComputeError, match="并非本次授权"):
        validate(
            {"evidenceRefs": [{"kind": "knowledge", "id": "1", "revision": 2}]},
            [{"kind": "knowledge", "id": "1", "revision": 1}],
        )
    with pytest.raises(ComputeError, match="未授权"):
        validate({"nextAction": "delete_all"})


def test_retry_feedback_includes_field_index_type_and_count():
    workflow, stage, results = ordinary_stage()
    bad = model_response("ecology-priority", [])
    bad["decision"]["findings"] = ["有效", 123]
    (_, _), requests = run(
        [bad, model_response("ecology-priority", [])], workflow, stage, results
    )
    error = json.loads(requests[1][-1]["content"])["validationError"]
    assert all(part in error for part in ("findings", "第2项", "int", "共2项"))
    assert json.loads(stage["modelAttempts"][0]["responseArtifact"]["content"]) == bad


def test_unavailable_query_field_is_named_in_feedback():
    with pytest.raises(ComputeError, match="未声明字段：knowledgeQuery"):
        validate({"knowledgeQuery": "不应检索"})


def test_audit_redacts_quoted_multiline_credentials():
    artifact = response_artifact(
        "password=\"private words\nsecond line\"; 密钥：'private key'"
    )
    assert "private" not in artifact["content"]
    assert "second line" not in artifact["content"]


def test_audit_redacts_credentials_and_bounds_utf8():
    artifact = response_artifact(
        'api_key="private-key" password=private-password Authorization: Bearer private-token sk-secretsecret '
        + "岩" * MAX_RESPONSE_BYTES
    )
    assert artifact["truncated"]
    assert len(artifact["content"].encode("utf-8")) <= MAX_RESPONSE_BYTES
    assert "已截断" in artifact["content"]
    assert all(
        secret not in artifact["content"]
        for secret in (
            "private-key",
            "private-password",
            "private-token",
            "sk-secretsecret",
        )
    )


def test_stream_failure_saves_partial_response_without_retry():
    workflow, stage, results = ordinary_stage()

    def broken(*args, **kwargs):
        yield "部分正文"
        raise ModelError("连接中断")

    persisted = []
    with (
        patch("apps.agent.demo_decisions.provider.stream", side_effect=broken),
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=800),
        pytest.raises(ModelError, match="连接中断"),
    ):
        from apps.agent.demo_decisions import decide
        from apps.agent.policy import default_policy

        decide(
            workflow,
            None,
            default_policy(),
            stage,
            results,
            lambda: None,
            on_attempt=lambda record: persisted.append(dict(record)),
        )
    assert len(stage["modelAttempts"]) == 1
    assert persisted[-1]["responseArtifact"]["content"] == "部分正文"
    assert persisted[-1]["status"] == "failed"
