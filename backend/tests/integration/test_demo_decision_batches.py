"""Real decision assembly reviews every member through bounded provider requests."""

# ruff: noqa: F811

import copy
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from apps.agent.decision_budget import (
    BudgetReviewRequired,
    assert_visible_edits,
    project_payload,
)
from apps.agent.demo_decisions import decide
from apps.agent.demo_decision_batches import (
    MAX_BATCH_GROUPS,
    MAX_BATCH_ROWS,
    batch_payload,
    model_issue_groups,
    plan_batches,
    review_issues,
)
from apps.agent.demo_results import read_output
from apps.agent.geology_multi_review import (
    assess_edits,
    proposal,
    validate_alteration_actions,
)
from apps.agent.policy import default_policy
from apps.compute.packages import ComputeError
from tests.integration.test_decision_input_budget import expand
from tests.integration.test_demo_decision_retry import retry_model  # noqa: F401


def scenario(count=257):
    stage = {"name": "apply", "identifier": "geology-multi-apply", "parameters": {}}
    entry = {
        "id": 200,
        "revision": 3,
        "title": "实际地区试用规则",
        "conditions": ["逐对象面积实测且边界关系已核实"],
        "exceptions": ["边界不明确则保留人工核查"],
        "sources": [{"title": "实测记录", "locator": "1"}],
        "trialBinding": {"ruleId": "L-01", "ruleVersion": "trial-1"},
        "ruleConfig": {"area_m2": {"lt": 1000}},
    }
    workflow = SimpleNamespace(
        model="online-fixture",
        workflow_type="geology_multi_element_reasoning",
        goal="对完整实际对象逐项提出有据建议",
        evidence=[entry],
        iteration=1,
        max_iterations=99,
        plan={
            "stages": [
                {
                    "name": "check",
                    "identifier": "geology-multi-check",
                    "taskId": "task",
                },
                stage,
            ],
            "algorithms": {},
            "trialRuleBindings": [{"id": 200, "revision": 3, **entry["trialBinding"]}],
            "actualModelCallCount": 0,
        },
    )
    rows = [
        {
            "issue_id": f"issue-{index}",
            "feature_id": f"object-{index}",
            "element": "lithology",
            "rule_id": "L-01",
            "rule_version": "trial-1",
            "snapshot_hash": "a" * 64,
            "allowed_actions_json": '["set_code","review","keep"]',
            "suggested_action": "set_code",
            "status": "suggested",
            "target_code": "T3",
            "conditions": "面积和边界均须满足",
            "exceptions": "边界不明确保持原样",
            "measurements_json": json.dumps({"area_m2": index + 1}),
            "reason": "已实际测量，待按知识核对",
            "geometry_json": '{"type":"Polygon","coordinates":[[[90,30],[91,30],[91,31],[90,31],[90,30]]]}',
        }
        for index in range(count)
    ]
    results = [
        {
            "key": "issues",
            "outputId": 1,
            "taskId": "task",
            "checksum": "c" * 64,
            "rows": rows,
        },
        {
            "key": "statistics",
            "outputId": 2,
            "taskId": "task",
            "checksum": "d" * 64,
            "rows": [{"objects": count}],
        },
    ]
    return workflow, stage, results


def restore_member(group, sample):
    member = copy.deepcopy({**group["memberCommon"], **sample})
    values = member.pop("measurements")
    absent = set(member.pop("measurementAbsentColumns", []))
    measured = copy.deepcopy(group["measurementCommon"])
    measured.update(
        {
            key: values[index]
            for index, key in enumerate(group["measurementColumns"])
            if index not in absent
        }
    )
    measured.update(
        {key: member[field] for key, field in group["measurementAliases"].items()}
    )
    member["measurements_json"] = measured
    return member


def provider_fixture(requests, seen, fail_at=None, disposition=None):
    def stream(model, messages, output, guard, **options):
        requests.append(copy.deepcopy(messages))
        if fail_at == len(requests):
            raise ComputeError("流式连接中断")
        payload = json.loads(messages[1]["content"])
        payload = expand(payload, payload.get("contextDefinitions", {}))
        assert output == 2000
        assert payload["modelBatch"]["completeMembers"] is True
        groups = payload["actualResults"][0]["groups"]
        for group in groups:
            assert len(group["samples"]) == group["count"]
            for row in group["samples"]:
                row = {**group.get("memberCommon", {}), **row}
                assert "geometry_json" not in row
                assert (
                    row["conditions"]
                    and row["exceptions"]
                    and group["memberSource"]["checksum"]
                )
                seen.append(row["issue_id"])
        value = {
            "decision": {
                "problem": "逐成员检视本批真实证据",
                "findings": ["本批实测值及边界满足试用条件"],
                "judgement": "提交本批有据建议",
                "uncertainties": ["人工批准后方可执行"],
                "nextAction": "geology-multi-apply",
                "algorithmReason": "核对本批全部成员及规则例外",
                "evidenceRefs": [
                    {"kind": "output", "id": "2"},
                    {"kind": "knowledge", "id": "200", "revision": 3},
                ],
                "resultSummary": "仅提出本批范围的建议",
            },
            "edits": [
                {
                    "group_id": group["group_id"],
                    "disposition": disposition
                    or ("suggested" if group["status"] == "suggested" else "review"),
                    "excluded_issue_ids": [],
                    "reason": "核对本批各对象测量与知识条件，例外保留",
                }
                for group in groups
            ],
        }
        if disposition == "omit":
            value["edits"] = []
        return iter([json.dumps(value, ensure_ascii=False)])

    return stream


def run(workflow, stage, results, requests, seen, *, fail_at=None, disposition=None):
    def record(attempt):
        if attempt["status"] == "requesting":
            if workflow.plan["actualModelCallCount"] >= workflow.max_iterations:
                attempt.update(status="budget_blocked", accepted=False)
                raise ComputeError("已达到场景真实模型请求次数上限")
            workflow.plan["actualModelCallCount"] += 1
            attempt["requested"] = True

    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=65536),
        patch(
            "apps.agent.context.count_tokens",
            side_effect=lambda model, messages, *args: (
                sum(len(item["content"].encode()) for item in messages) // 4 + 64
            ),
        ),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            side_effect=provider_fixture(requests, seen, fail_at, disposition),
        ),
    ):
        return decide(
            workflow, None, default_policy(), stage, results, lambda: None, record
        )


@pytest.mark.parametrize("count,expected_batches", [(257, 3), (541, 5)])
def test_all_members_are_reviewed_once_and_same_group_expands_only_current_scope(
    retry_model,
    count,
    expected_batches,
):
    workflow, stage, results = scenario(count)
    original = copy.deepcopy(results)
    requests, seen = [], []
    decision, edits = run(workflow, stage, results, requests, seen)
    assert len(requests) == expected_batches and workflow.plan[
        "actualModelCallCount"
    ] == len(requests)
    assert len(seen) == len(set(seen)) == len(edits) == count
    assert {item["issue_id"] for item in edits} == {
        row["issue_id"] for row in results[0]["rows"]
    }
    assert stage["modelBatches"]["coveredMemberCount"] == count
    for index, batch in enumerate(stage["modelBatches"]["batches"], 1):
        assert len(batch["stage"]["edits"]) == batch["end"] - batch["start"]
        for attempt in batch["stage"]["modelAttempts"]:
            assert attempt["batchIndex"] == index
            assert attempt["inputTokens"] <= attempt["inputLimit"] == 15000
            assert attempt["outputLimit"] == 2000 and attempt["truncated"] is False
    assert decision["nextAction"] == "geology-multi-apply" and results == original
    recovered = run(workflow, stage, results, requests, seen)
    assert recovered == (decision, edits)
    assert workflow.plan["actualModelCallCount"] == len(requests)
    assert len(seen) == count


def test_requested_interrupted_batch_is_not_sent_again(retry_model):
    workflow, stage, results = scenario()
    requests, seen = [], []
    with pytest.raises(ComputeError, match="流式连接中断"):
        run(workflow, stage, results, requests, seen, fail_at=2)
    assert stage["modelBatches"]["cursor"] == 1
    with pytest.raises(ComputeError, match="完整分析响应未保存"):
        run(workflow, stage, results, requests, seen)
    assert len(requests) == workflow.plan["actualModelCallCount"] == 2


def test_interleaved_groups_are_packed_with_original_row_locators_and_full_coverage(
    retry_model,
):
    workflow, stage, results = scenario(100)
    for index, row in enumerate(results[0]["rows"]):
        row["conditions"] = f"实测条件-{index % 10}"
    original = copy.deepcopy(results)
    requests, seen = [], []
    _, edits = run(workflow, stage, results, requests, seen)
    assert len(requests) == 2
    assert len(edits) == len(seen) == len(set(seen)) == 100
    locators = []
    for request in requests:
        projected = json.loads(request[1]["content"])
        value = expand(projected, projected.get("contextDefinitions", {}))
        groups = value["actualResults"][0]["groups"]
        assert len(groups) <= MAX_BATCH_GROUPS
        assert value["modelBatch"]["memberCount"] <= MAX_BATCH_ROWS
        for group in groups:
            for member in group["samples"]:
                restored = restore_member(group, member)
                index = restored.pop("sourceRowIndex")
                locators.append(index)
                assert restored == {
                    key: json.loads(cell) if key == "measurements_json" else cell
                    for key, cell in original[0]["rows"][index].items()
                    if key != "geometry_json"
                }
    assert sorted(locators) == list(range(100))
    assert locators != list(range(100)) and results == original


def test_heterogeneous_targets_remain_per_member_when_one_model_group_expands(
    retry_model,
):
    workflow, stage, results = scenario(36)
    for index, row in enumerate(results[0]["rows"]):
        row["target_code"] = f"T{index % 12}"
    requests, seen = [], []
    _, edits = run(workflow, stage, results, requests, seen)
    assert len(requests) == 1 and len(model_issue_groups(results[0]["rows"])) == 1
    projected = json.loads(requests[0][1]["content"])
    value = expand(projected, projected.get("contextDefinitions", {}))
    group = value["actualResults"][0]["groups"][0]
    assert group["target_code"] is None and group["targetCodeMode"] == "per_member"
    assert group["targetCodeDistribution"] == {f"T{i}": 3 for i in range(12)}
    assert "target_code" not in group["memberCommon"]
    assert {row["issue_id"]: row["target_code"] for row in edits} == {
        row["issue_id"]: row["target_code"] for row in results[0]["rows"]
    }


def test_original_issue_priority_wins_even_when_its_model_batch_runs_later(retry_model):
    workflow, stage, results = scenario(257)
    original_first = results[0]["rows"][0]
    packed_first = results[0]["rows"][1]
    original_first.update(
        conditions=original_first["conditions"] + " · source-first",
        target_code="source-first-code",
    )
    packed_first.update(
        feature_id=original_first["feature_id"], target_code="early-batch-code"
    )
    requests, seen = [], []
    decision, edits = run(workflow, stage, results, requests, seen)
    assert seen.index(packed_first["issue_id"]) < seen.index(original_first["issue_id"])
    assert len(requests) == 3 and len(edits) == 256
    selected = next(
        edit for edit in edits if edit["issue_id"] == original_first["issue_id"]
    )
    assert selected["target_code"] == "source-first-code"
    assert packed_first["issue_id"] not in {edit["issue_id"] for edit in edits}
    assert edits[0]["issue_id"] == original_first["issue_id"]
    assert run(workflow, stage, results, requests, seen) == (decision, edits)
    assert len(requests) == 3


def test_source_change_and_completed_edit_tampering_stop_before_new_request(
    retry_model,
):
    workflow, stage, results = scenario(5)
    requests, seen = [], []
    run(workflow, stage, results, requests, seen)
    stage["modelBatches"]["batches"][0]["stage"]["edits"][0]["target_code"] = "forged"
    with pytest.raises(ComputeError, match="实际模型响应不一致"):
        run(workflow, stage, results, requests, seen)
    results[0]["rows"][-1]["measurements_json"] = '{"area_m2":9999}'
    with pytest.raises(ComputeError, match="已变化"):
        run(workflow, stage, results, requests, seen)
    assert len(requests) == 1


def test_generic_large_tables_are_bounded_from_first_request_with_complete_source_identity():
    workflow, stage, results = scenario(5000)
    payload = {"actualResults": results, "knowledge": [], "inputRoles": []}
    original = copy.deepcopy(payload)
    projected = project_payload(payload, 0)
    assert len(projected["actualResults"][0]["rows"]) <= 40
    summary = projected["evidenceProjection"][0]
    assert summary["inputCount"] == 5000 and summary["omittedCount"] > 4900
    assert summary["sourceSha256"] and summary["coverage"] == "shown_items_only"
    shown = {row["issue_id"] for row in projected["actualResults"][0]["rows"]}
    unseen = next(row for row in results[0]["rows"] if row["issue_id"] not in shown)
    with pytest.raises(ValueError, match="未在本次.*模型证据中展示"):
        assert_visible_edits([{"issue_id": unseen["issue_id"]}], projected)
    assert payload == original


def test_unrequested_budget_block_resumes_after_explicit_budget_adjustment(retry_model):
    workflow, stage, results = scenario(257)
    workflow.max_iterations = 1
    requests, seen = [], []
    with pytest.raises(BudgetReviewRequired, match="进度和审计已保留"):
        run(workflow, stage, results, requests, seen)
    assert stage["modelBatches"]["cursor"] == 1
    assert len(requests) == 1
    workflow.max_iterations = 99
    stage.pop("contextBudgetReview")
    decision, edits = run(workflow, stage, results, requests, seen)
    assert len(edits) == len(seen) == len(set(seen)) == 257
    assert len(requests) == workflow.plan["actualModelCallCount"]
    assert (
        stage["modelBatches"]["batches"][1]["stage"]["unrequestedBudgetAttempts"][0][
            "requested"
        ]
        is False
    )


def test_held_objects_in_separate_batches_are_covered_without_becoming_edits(
    retry_model,
):
    workflow, stage, results = scenario(257)
    results[0]["rows"][0]["status"] = "review"
    results[0]["rows"][128]["status"] = "exception"
    requests, seen = [], []
    _, edits = run(workflow, stage, results, requests, seen)
    assert len(seen) == len(set(seen)) == 257
    assert len(edits) == 255
    assert not {"issue-0", "issue-128"}.intersection(item["issue_id"] for item in edits)


@pytest.mark.parametrize("count", [101, 10000, 10001])
def test_large_generic_result_is_read_completely_with_a_hard_source_limit(
    tmp_path, count
):
    source = tmp_path / "actual.csv"
    source.write_text(
        "object_id,value\n" + "".join(f"o{i},{i}\n" for i in range(count))
    )
    output = SimpleNamespace(
        id=1,
        task_id="task",
        path="actual.csv",
        expired=False,
        key="statistics",
        kind="table",
        checksum=hashlib.sha256(source.read_bytes()).hexdigest(),
        metadata={},
    )
    workflow = SimpleNamespace(owner_id=1, workflow_type="ecology_change", steps=Mock())
    workflow.steps.filter.return_value.exists.return_value = True
    task = SimpleNamespace(id="task", owner_id=1, status="succeeded")
    with (
        patch("apps.agent.demo_results.authorized_task", return_value=task),
        patch("apps.agent.demo_results.app_path", return_value=source),
    ):
        if count > 10000:
            with pytest.raises(ComputeError, match="超过10000行"):
                read_output(workflow, None, {}, output)
        else:
            result = read_output(workflow, None, {}, output)
            assert len(result["rows"]) == result["rowCount"] == count
            assert result["checksum"] == output.checksum and result["scope"] == "all"
            assert (
                len(
                    project_payload({"actualResults": [result]}, 0)["actualResults"][0][
                        "rows"
                    ]
                )
                == 40
            )


def raster_scenario(count=541):
    workflow, stage, results = scenario(count)
    workflow.evidence[0]["trialBinding"]["ruleId"] = "A-05"
    workflow.plan["trialRuleBindings"][0]["ruleId"] = "A-05"
    workflow.plan["algorithms"] = {
        "geology-multi-check": {
            "manifest": {"outputs": [{"key": "alteration_summary"}]}
        }
    }
    summaries = []
    for index, row in enumerate(results[0]["rows"]):
        row.update(
            element="alteration",
            feature_id=f"AG-{index}",
            rule_id="A-05",
            target_code="",
            suggested_action="downweight",
            allowed_actions_json='["keep","downweight","exclude","review"]',
            measurements_json=json.dumps(
                {
                    "raster_protocol": "alteration-pixels-v1",
                    "pixel_count": 100 + index,
                    "area_m2": 1000 + index,
                    "mineral": "chlorite",
                    "rock_group": "siliciclastic",
                    "boundary": "interior",
                }
            ),
        )
        summaries.append(
            {
                "rule_id": "A-05",
                "rule_version": "trial-1",
                "knowledge_id": 200,
                "knowledge_revision": 3,
                "mineral": "chlorite",
                "rock_group": "siliciclastic",
                "boundary": "interior",
                "suggested_action": "downweight",
                "status": "suggested",
                "unit_code": f"unit-{index}",
                "pixel_count": 100 + index,
                "area_m2": 1000 + index,
                "component_count": 1,
            }
        )
    results.append(
        {
            "key": "alteration_summary",
            "outputId": 3,
            "taskId": "task",
            "checksum": "e" * 64,
            "rows": summaries,
        }
    )
    return workflow, stage, results


@pytest.mark.parametrize("disposition", ["suggested", "keep", "review", "reject"])
def test_heterogeneous_raster_members_keep_exact_evidence_and_only_visible_scope_expands(
    retry_model, disposition
):
    workflow, stage, results = raster_scenario(140)
    for index, row in enumerate(results[0]["rows"]):
        measured = json.loads(row["measurements_json"])
        measured.update(
            mineral=["chlorite", "calcite"][index % 2],
            rock_group=["carbonate", "granite", "clastic"][index % 3],
            boundary=bool(index % 2),
        )
        row["measurements_json"] = json.dumps(measured)
    original = copy.deepcopy(results)
    assert len(model_issue_groups(results[0]["rows"])) == 1
    requests, seen = [], []
    _, edits = run(workflow, stage, results, requests, seen, disposition=disposition)
    assert len(requests) == 2 and len(seen) == len(set(seen)) == 140
    assert len(edits) == (140 if disposition in {"suggested", "keep"} else 0)
    scope = review_issues(workflow, results)[:128]
    payload = batch_payload(
        {
            "knowledge": [],
            "availableEvidence": [],
            "actualResults": results,
            "inputRoles": [],
        },
        results,
        scope,
        1,
    )
    group = payload["actualResults"][0]["groups"][0]
    assert len(group["samples"]) == group["count"] == 128
    assert group["modelGroupKind"] == "complete_raster_units"
    for member in group["samples"]:
        restored = restore_member(group, member)
        source = original[0]["rows"][restored["sourceRowIndex"]]
        assert restored["measurements_json"] == json.loads(source["measurements_json"])
    scoped = [{**results[0], "rows": results[0]["rows"][:128]}]
    scoped_edits, _ = assess_edits(
        [
            {
                "group_id": group["group_id"],
                "disposition": disposition,
                "excluded_issue_ids": [],
                "reason": "逐成员核对原始矿物、岩性背景与边界",
            }
        ],
        scoped,
        model_payload=payload,
    )
    assert not {f"issue-{i}" for i in range(128, 140)}.intersection(
        row["issue_id"] for row in scoped_edits
    )
    assert results == original


def raster_geometry_scenario():
    workflow, stage, results = raster_scenario(2)
    for index, row in enumerate(results[0]["rows"]):
        measured = json.loads(row["measurements_json"])
        measured.update(
            bbox=[90 + index, 30, 91 + index, 31],
            representatives=[
                {"area_m2": 50, "bbox": [90, 30, 91, 31], "detail": {"value": index}},
                {"area_m2": 25, "bbox": [91, 30, 92, 31]},
            ],
            additional_measurements={"values": [index, 1, 2]},
        )
        row["measurements_json"] = json.dumps(measured)
    return workflow, stage, results


def geometry_payload(workflow, results):
    return batch_payload(
        {
            "knowledge": workflow.evidence,
            "availableEvidence": [
                {
                    "kind": "knowledge",
                    "id": str(entry["id"]),
                    "revision": entry["revision"],
                }
                for entry in workflow.evidence
            ],
            "actualResults": results,
            "inputRoles": [],
        },
        results,
        review_issues(workflow, results),
        1,
    )


def test_raster_geometry_projection_only_omits_named_coordinate_paths_and_preserves_source():
    workflow, _, results = raster_geometry_scenario()
    original = copy.deepcopy(results)
    payload = geometry_payload(workflow, results)
    group = payload["actualResults"][0]["groups"][0]
    for sample in group["samples"]:
        restored = restore_member(group, sample)
        source = original[0]["rows"][restored["sourceRowIndex"]]
        expected = json.loads(source["measurements_json"])
        expected.pop("bbox")
        for representative in expected["representatives"]:
            representative.pop("bbox")
        assert restored["measurements_json"] == expected
        assert restored["geometryStoredInOriginal"] is True
        assert restored["omittedGeometryPaths"] == [
            "measurements_json.bbox",
            "measurements_json.representatives[].bbox",
        ]
        assert restored["snapshot_hash"] == source["snapshot_hash"]
    assert group["memberSource"]["checksum"] == original[0]["checksum"]
    assert "不能声称已做原始几何或空间复核" in payload["modelBatch"]["instruction"]
    assert results == original


@pytest.mark.parametrize("field", ["conditions", "exceptions", "ruleConfig"])
def test_bound_coordinate_predicates_require_full_original_measurements(field):
    workflow, _, results = raster_geometry_scenario()
    workflow.evidence[0][field] = (
        {"field": "representatives[0].bbox", "operator": "intersects"}
        if field == "ruleConfig"
        else ["须核查原始bbox坐标后判断"]
    )
    payload = geometry_payload(workflow, results)
    group = payload["actualResults"][0]["groups"][0]
    for sample in group["samples"]:
        restored = restore_member(group, sample)
        source = results[0]["rows"][restored["sourceRowIndex"]]
        assert restored["measurements_json"] == json.loads(source["measurements_json"])
        assert "omittedGeometryPaths" not in restored


@pytest.mark.parametrize("protocol", ["alteration-vector-v1", ""])
def test_geometry_projection_does_not_change_other_measurement_protocols(protocol):
    workflow, _, results = raster_geometry_scenario()
    for row in results[0]["rows"]:
        measured = json.loads(row["measurements_json"])
        measured["raster_protocol"] = protocol
        row["measurements_json"] = json.dumps(measured)
    payload = geometry_payload(workflow, results)
    group = payload["actualResults"][0]["groups"][0]
    for sample in group["samples"]:
        restored = restore_member(group, sample)
        assert restored["measurements_json"] == json.loads(
            results[0]["rows"][restored["sourceRowIndex"]]["measurements_json"]
        )


def test_batch_defers_unbound_background_without_citing_unread_text_or_mutating_source():
    workflow, _, results = raster_geometry_scenario()
    background = {
        "id": 201,
        "revision": 4,
        "title": "背景资料",
        "conditions": ["需坐标核查的背景"],
        "explanation": "原始背景正文",
    }
    workflow.evidence.append(background)
    original = copy.deepcopy(workflow.evidence)
    payload = geometry_payload(workflow, results)
    assert payload["knowledge"] == [original[0]]
    assert payload["batchKnowledgeScope"]["deferredBackground"] == [
        {"id": 201, "revision": 4, "title": "背景资料"}
    ]
    assert [ref["id"] for ref in payload["availableEvidence"]] == ["200"]
    group = payload["actualResults"][0]["groups"][0]
    assert group["memberCommon"]["omittedGeometryPaths"]
    assert workflow.evidence == original


def test_batch_without_bound_knowledge_retains_complete_original_knowledge():
    workflow, _, results = raster_geometry_scenario()
    workflow.evidence[0].pop("trialBinding")
    original = copy.deepcopy(workflow.evidence)
    payload = geometry_payload(workflow, results)
    assert payload["knowledge"] == original
    assert "batchKnowledgeScope" not in payload


def test_batch_rule_table_counts_describe_selected_rows_and_preserve_original_reading():
    workflow, _, results = raster_scenario(2)
    role = {
        "role": "rules",
        "rows": [{"rule_id": "A-05"}, {"rule_id": "A-01"}],
        "rowCount": 2,
        "scope": "all",
        "readingScope": {"truncated": False, "rowCount": 2},
    }
    original = copy.deepcopy(role)
    payload = batch_payload(
        {
            "knowledge": workflow.evidence,
            "availableEvidence": [],
            "actualResults": results,
            "inputRoles": [role],
        },
        results,
        review_issues(workflow, results),
        1,
    )
    selected = payload["inputRoles"][0]
    assert selected["rows"] == [{"rule_id": "A-05"}]
    assert selected["rowCount"] == 1 and selected["scope"] == "batch_rule_bindings"
    assert selected["sourceRowCount"] == 2 and selected["sourceScope"] == "all"
    assert selected["readingScope"]["originalReading"] == original["readingScope"]
    assert selected["readingScope"]["sourceRowsSha256"] and role == original


def test_measurement_columns_roundtrip_every_nested_value_missing_null_and_source_alias():
    workflow, _, results = raster_scenario(236)
    for index, row in enumerate(results[0]["rows"]):
        measured = json.loads(row["measurements_json"])
        measured.update(
            group_id=row["feature_id"],
            nested={"flags": [True, None, False], "values": [index, 1.23456789]},
            typed_scalar=[True, 1, 1.0][index % 3],
            typed_nested={"value": [[True, 1, 1.0][index % 3]]},
            optional=None,
        )
        if index % 2:
            measured.pop("optional")
        row["measurements_json"] = json.dumps(measured)
    original = copy.deepcopy(results)
    rows = review_issues(workflow, results)
    covered = []
    for start in range(0, len(rows), MAX_BATCH_ROWS):
        payload = batch_payload(
            {
                "knowledge": workflow.evidence,
                "availableEvidence": [],
                "actualResults": results,
                "inputRoles": [],
            },
            results,
            rows[start : start + MAX_BATCH_ROWS],
            start // MAX_BATCH_ROWS + 1,
        )
        for group in payload["actualResults"][0]["groups"]:
            assert group["measurementAliases"] == {"group_id": "feature_id"}
            for sample in group["samples"]:
                restored = restore_member(group, sample)
                index = restored["sourceRowIndex"]
                assert json.dumps(
                    restored["measurements_json"], sort_keys=True
                ) == json.dumps(
                    json.loads(original[0]["rows"][index]["measurements_json"]),
                    sort_keys=True,
                )
                assert len(sample["measurements"]) == len(group["measurementColumns"])
                covered.append(index)
    assert sorted(covered) == list(range(236)) and results == original


@pytest.mark.parametrize("count,expected_batches", [(1, 1), (541, 5)])
def test_every_raster_unit_is_explicitly_reviewed_and_only_scoped_edits_expand(
    retry_model, count, expected_batches
):
    workflow, stage, results = raster_scenario(count)
    requests, seen = [], []
    decision, edits = run(workflow, stage, results, requests, seen)
    assert len(requests) == expected_batches
    assert len(edits) == len(seen) == len(set(seen)) == count
    assert all(
        item["action"] == "downweight" and item["weight"] == 0.5 for item in edits
    )
    assert stage["modelBatches"]["coveredMemberCount"] == count
    review, rows = proposal(workflow, {"decision": decision, "edits": edits}, results)
    assert len(rows) == count
    assert all(item["origin"] == "model_reviewed" for item in review["suggestions"])
    recovered = run(workflow, stage, results, requests, seen)
    assert recovered == (decision, edits) and len(requests) == expected_batches


@pytest.mark.parametrize("disposition", ["keep", "reject", "review"])
def test_raster_keep_reject_and_review_are_never_refilled_from_operator_candidate(
    retry_model, disposition
):
    workflow, stage, results = raster_scenario(9)
    requests, seen = [], []
    decision, edits = run(
        workflow, stage, results, requests, seen, disposition=disposition
    )
    review, rows = proposal(workflow, {"decision": decision, "edits": edits}, results)
    assert len(seen) == 9
    if disposition == "keep":
        assert len(rows) == 9 and all(
            row["action"] == "keep" and row["weight"] == 1 for row in rows
        )
        assert all(
            item["action"] == "keep" and item["origin"] == "model_reviewed"
            for item in review["suggestions"]
        )
    else:
        assert edits == rows == review["suggestions"] == []


def test_omitted_raster_group_fails_explicit_coverage_and_never_creates_suggestions(
    retry_model,
):
    workflow, stage, results = raster_scenario(9)
    requests, seen = [], []
    with pytest.raises(ComputeError, match="尚未明确处置"):
        run(workflow, stage, results, requests, seen, disposition="omit")
    assert len(requests) == 2 and stage["modelBatches"]["cursor"] == 0
    review, rows = proposal(
        workflow, {"edits": [], "decision": {"evidenceRefs": []}}, results
    )
    assert rows == review["suggestions"] == []


def test_raster_user_override_obeys_snapshot_actions_and_preserves_model_choice(
    retry_model,
):
    workflow, stage, results = raster_scenario(1)
    results[0]["rows"][0]["allowed_actions_json"] = '["keep","downweight","review"]'
    decision, edits = run(workflow, stage, results, [], [], disposition="keep")
    review, rows = proposal(workflow, {"decision": decision, "edits": edits}, results)
    selected = {review["suggestions"][0]["id"]}
    assert review["suggestions"][0]["action"] == "keep"
    with pytest.raises(ComputeError, match="允许动作"):
        validate_alteration_actions(review, selected, {"AG-0": "exclude"})
    assert validate_alteration_actions(review, selected, {"AG-0": "downweight"}) == {
        "AG-0": "downweight"
    }


@pytest.mark.parametrize("tokens_per_member,expected_batches", [(20, 3), (200, 5)])
def test_preflight_packs_with_production_token_gate_without_generation_and_execution_matches_plan(
    retry_model,
    tokens_per_member,
    expected_batches,
):
    workflow, stage, results = raster_scenario(257)
    stage.update(status="needs_review", outputs=[{"outputId": 92}])
    policy = default_policy()

    def tokenizer(model, messages, *args):
        payload = json.loads(messages[1]["content"])
        value = expand(payload, payload.get("contextDefinitions", {}))
        return 4000 + tokens_per_member * value["modelBatch"]["memberCount"]

    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=65536),
        patch("apps.agent.context.count_tokens", side_effect=tokenizer),
        patch("apps.agent.demo_decisions.provider.stream") as stream,
    ):
        plan = plan_batches(
            workflow, None, policy, stage, results, lambda: None, context=[]
        )
    stream.assert_not_called()
    assert len(plan["batches"]) == expected_batches
    assert workflow.plan["actualModelCallCount"] == 0 and "modelBatches" not in stage
    assert all(
        item["inputTokens"] <= item["inputLimit"] == 15000 for item in plan["batches"]
    )
    stage["modelBatches"] = {
        "sourceSha256": plan["sourceSha256"],
        "memberCount": plan["memberCount"],
        "cursor": 0,
        "batches": [],
        "preflight": plan,
        "status": "planned",
    }
    requests, seen = [], []

    def record(attempt):
        if attempt["status"] == "requesting":
            workflow.plan["actualModelCallCount"] += 1
            attempt["requested"] = True

    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=65536),
        patch("apps.agent.context.count_tokens", side_effect=tokenizer) as counted,
        patch(
            "apps.agent.demo_decisions.provider.stream",
            side_effect=provider_fixture(requests, seen),
        ),
    ):
        _, edits = decide(workflow, None, policy, stage, results, lambda: None, record)
    assert counted.call_count == expected_batches
    assert stage["status"] == "needs_review" and stage["outputs"] == [{"outputId": 92}]
    assert all(
        "status" not in batch["stage"] and "outputs" not in batch["stage"]
        for batch in stage["modelBatches"]["batches"]
    )
    assert len(requests) == workflow.plan["actualModelCallCount"] == expected_batches
    assert len(edits) == len(seen) == len(set(seen)) == 257
    assert [
        batch["stage"]["modelAttempts"][0]["requestSha256"]
        for batch in stage["modelBatches"]["batches"]
    ] == [item["requestSha256"] for item in plan["batches"]]


def test_feedback_drift_after_preflight_blocks_generation_before_call_accounting(
    retry_model,
):
    workflow, stage, results = raster_scenario(2)
    policy = default_policy()
    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=65536),
        patch("apps.agent.context.count_tokens", return_value=800),
        patch("apps.agent.demo_decisions._human_feedback", return_value=[]),
        patch("apps.agent.demo_decisions.provider.stream") as planning_stream,
    ):
        plan = plan_batches(
            workflow, None, policy, stage, results, lambda: None, context=[]
        )
    planning_stream.assert_not_called()
    stage["modelBatches"] = {
        "sourceSha256": plan["sourceSha256"],
        "memberCount": plan["memberCount"],
        "cursor": 0,
        "batches": [],
        "preflight": plan,
        "status": "planned",
    }
    feedback = [
        {
            "stepSequence": 8,
            "decision": "approve",
            "feedback": "增加一项尚未纳入冻结请求的现场核查意见",
            "stage": "check",
            "reviewedOutputs": [],
        }
    ]
    record = Mock()
    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=65536),
        patch("apps.agent.context.count_tokens", return_value=800) as counted,
        patch("apps.agent.demo_decisions._human_feedback", return_value=feedback),
        patch("apps.agent.demo_decisions.provider.stream") as stream,
        pytest.raises(BudgetReviewRequired, match="冻结的分批预算计划不同"),
    ):
        decide(workflow, None, policy, stage, results, lambda: None, record)
    stream.assert_not_called()
    record.assert_not_called()
    assert counted.call_count == 1
    assert workflow.plan["actualModelCallCount"] == 0
    state = stage["modelBatches"]
    assert state["status"] == "paused" and state["cursor"] == 0
    child = state["batches"][0]["stage"]
    assert not child.get("modelAttempts")
    for review in (stage["contextBudgetReview"], child["contextBudgetReview"]):
        assert review["kind"] == "preflight_request_changed"
        assert review["requested"] is False
        assert review["expectedRequestSha256"] == plan["batches"][0]["requestSha256"]
        assert review["actualRequestSha256"] != review["expectedRequestSha256"]
    assert child["modelRequestPayload"]["humanReviewFeedback"] == feedback


def test_irreducible_preflight_preserves_parent_input_review_audit_without_generation(
    retry_model,
):
    workflow, stage, results = raster_scenario(1)
    with (
        patch("apps.agent.demo_decisions.provider.model_window", return_value=65536),
        patch("apps.agent.context.count_tokens", return_value=20000),
        patch("apps.agent.demo_decisions.provider.stream") as stream,
        pytest.raises(BudgetReviewRequired),
    ):
        plan_batches(
            workflow, None, default_policy(), stage, results, lambda: None, context=[]
        )
    stream.assert_not_called()
    assert stage["contextBudgetReview"]["kind"] == "input_budget"
    assert stage["contextBudgetReview"]["requested"] is False
    assert stage["modelRequestPayload"]["modelBatch"]["memberCount"] == 1
    assert stage["modelRequestInstruction"] and "modelAttempts" not in stage


def test_bounded_error_display_cannot_hide_an_unreviewed_raster_unit():
    workflow, stage, results = raster_scenario(1)
    edits = [
        {
            "issue_id": f"missing-{i}",
            "action": "downweight",
            "target_code": "",
            "weight": 0.5,
            "reason": "无效对象",
        }
        for i in range(100)
    ]
    edits.append(
        {
            "issue_id": "issue-0",
            "action": "downweight",
            "target_code": "",
            "weight": 2,
            "reason": "非法权重",
        }
    )
    rows, assessment = assess_edits(
        edits, results, model_payload={"actualResults": results}
    )
    assert not rows and len(assessment["errors"]) <= 30
    assert not any(error.get("issue_id") == "issue-0" for error in assessment["errors"])
    assert assessment["unreviewedRasterCount"] == 1
