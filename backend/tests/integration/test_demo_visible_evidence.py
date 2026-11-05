"""A declared source is not citable when deferred from the actual model view."""

import copy
import json

import pytest

from apps.agent.demo_decisions import (
    _validate_response,
    decision_payload,
    evidence_refs,
)
from apps.agent.demo_decision_batches import batch_payload
from apps.compute.packages import ComputeError
from tests.integration.test_demo_decision_retry import ordinary_stage
from tests.integration.test_demo_decision_batches import scenario
from tests.integration.test_demo_edit_context import model_response


def evidence_case():
    workflow, stage, results = ordinary_stage()
    workflow.evidence = [
        {"id": 200, "revision": 3, "title": "当前阶段知识"},
        {"id": 201, "revision": 3, "title": "延期的远景知识"},
    ]
    refs = [
        {"kind": "output", "id": "102", "title": "本轮最新统计"},
        {"kind": "knowledge", "id": "200", "revision": 3, "title": "当前阶段知识"},
        {"kind": "knowledge", "id": "201", "revision": 3, "title": "延期的远景知识"},
    ]
    value = model_response(stage["identifier"], [])
    value["decision"]["evidenceRefs"] = [
        {"kind": "output", "id": 102, "revision": "模型附加的非知识字段"},
        {"kind": "knowledge", "id": 200, "revision": "3"},
    ]
    payload = {
        "availableEvidence": [refs[0], {**refs[1], "id": 200, "revision": "3"}],
        "actualResults": results,
    }
    return workflow, stage, results, refs, value, payload


def test_deferred_knowledge_is_rejected_even_when_authorized_in_complete_sources():
    workflow, stage, results, refs, value, payload = evidence_case()
    value["decision"]["evidenceRefs"][1] = {
        "kind": "knowledge",
        "id": "201",
        "revision": 3,
    }
    with pytest.raises(ComputeError, match="第2项并非本次授权"):
        _validate_response(
            json.dumps(value), workflow, stage, results, refs, model_payload=payload
        )


def test_visible_ids_and_revisions_normalize_to_original_canonical_reference_types():
    workflow, stage, results, refs, value, payload = evidence_case()
    original_refs = copy.deepcopy(refs)
    decision, edits = _validate_response(
        json.dumps(value), workflow, stage, results, refs, model_payload=payload
    )
    assert decision["evidenceRefs"] == refs[:2] and edits == []
    assert decision["evidenceRefs"][0]["id"] == "102"
    assert decision["evidenceRefs"][1]["revision"] == 3
    assert refs == original_refs


def test_visible_packet_cannot_grant_an_unauthorized_reference_or_wrong_revision():
    workflow, stage, results, refs, value, payload = evidence_case()
    for identity, revision in [(999, 3), (200, 4)]:
        payload["availableEvidence"][1] = {
            "kind": "knowledge",
            "id": identity,
            "revision": revision,
        }
        value["decision"]["evidenceRefs"][1] = payload["availableEvidence"][1]
        with pytest.raises(ComputeError, match="并非本次授权"):
            _validate_response(
                json.dumps(value), workflow, stage, results, refs, model_payload=payload
            )


def test_visible_batch_refs_preserve_valid_partial_edits_and_reject_deferred_citations():
    workflow, stage, results = scenario(2)
    workflow.evidence.append(
        {
            "id": 201,
            "revision": 3,
            "title": "后续远景规则",
            "trialBinding": {"ruleId": "P-01"},
        }
    )
    refs = evidence_refs(workflow, [], results)
    scope = [(results[0], index, row) for index, row in enumerate(results[0]["rows"])]
    payload = batch_payload(
        decision_payload(workflow, stage, [], results), results, scope, 1
    )
    value = model_response(stage["identifier"], [])
    value["decision"]["evidenceRefs"] = [
        {"kind": "output", "id": 2},
        {"kind": "knowledge", "id": 200, "revision": "3"},
    ]
    valid = {
        "issue_id": "issue-0",
        "action": "set_code",
        "target_code": "T3",
        "weight": 1,
        "reason": "依据本批完整测量和当前规则",
    }
    value["edits"] = [valid, {**valid, "issue_id": "not-visible"}]
    decision, edits = _validate_response(
        json.dumps(value),
        workflow,
        stage,
        results,
        refs,
        model_payload=payload,
        allow_partial=True,
    )
    assert edits == [valid] and stage["editValidation"]["discardedCount"] == 1
    assert decision["evidenceRefs"][1]["id"] == "200"
    value["decision"]["evidenceRefs"].append(
        {"kind": "knowledge", "id": "201", "revision": 3}
    )
    with pytest.raises(ComputeError, match="第3项并非本次授权"):
        _validate_response(
            json.dumps(value),
            workflow,
            stage,
            results,
            refs,
            model_payload=payload,
            allow_partial=True,
        )
