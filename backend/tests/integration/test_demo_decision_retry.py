"""Only bounded model response repairs may retry; evidence and limits stay intact."""

# ruff: noqa: F811

import copy
import hashlib
import json
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied

from apps.agent.demo_decisions import decide
from apps.agent.demo_results import EDIT_FIELDS
from apps.agent.policy import default_policy
from apps.agent.provider import ModelError
from apps.compute.packages import ComputeError
from tests.integration.test_demo_edit_context import geology, model_response
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo, scenario  # noqa: F401


@pytest.fixture
def retry_model(settings):
    settings.AGENT_MODELS = [
        {
            "alias": "online-fixture",
            "name": "实际provider接口测试",
            "model_id": "qwen-fixture",
            "base_url": "http://127.0.0.1:19100/v1",
            "agent": True,
        }
    ]


def responses(raws, requests):
    items = iter(raws)

    def stream(model, messages, output, guard, **options):
        requests.append(copy.deepcopy(messages))
        value = next(items)
        if isinstance(value, Exception):
            raise value
        options["on_usage"]({"prompt_tokens": 800, "completion_tokens": 200})
        return iter(
            [value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)]
        )

    return stream


def run(
    raws, workflow, stage, results, *, guard=lambda: None, callback=None, tokens=None
):
    requests = []
    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", side_effect=tokens or [800, 1200]),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            side_effect=responses(raws, requests),
        ),
    ):
        outcome = decide(
            workflow, None, default_policy(), stage, results, guard, callback
        )
    return outcome, requests


def ordinary_stage():
    workflow, stage, results = geology()
    stage["identifier"] = "ecology-priority"
    return workflow, stage, results


@pytest.mark.parametrize("output_limit", [2048, 8192, 16384])
def test_configured_output_limit_reaches_model_and_reserves_context(
    output_limit, retry_model
):
    workflow, stage, results = ordinary_stage()
    policy = {**default_policy(), "maxOutputTokens": output_limit}
    answer = model_response("ecology-priority", [])
    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=800),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            return_value=iter([json.dumps(answer)]),
        ) as stream,
    ):
        decision, edits = decide(workflow, None, policy, stage, results, lambda: None)
    assert decision["nextAction"] == "ecology-priority" and edits == []
    assert stream.call_args.args[2] == output_limit
    attempt = stage["modelAttempts"][0]
    assert attempt["outputLimit"] == output_limit
    assert attempt["inputLimit"] == min(
        policy["maxContextTokens"], 32768 - output_limit - 256
    )


def test_larger_output_reservation_still_rejects_oversized_input(retry_model):
    workflow, stage, results = ordinary_stage()
    policy = {**default_policy(), "maxOutputTokens": 8192}
    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=25000),
        patch("apps.agent.demo_decisions.provider.stream") as stream,
        pytest.raises(ModelError, match="25000 token，可用 24320"),
    ):
        decide(workflow, None, policy, stage, results, lambda: None)
    stream.assert_not_called()
    assert not stage.get("modelAttempts")


def test_wrong_statistics_retries_real_model_without_adding_refs(retry_model):
    workflow, stage, results = ordinary_stage()
    initial_results = copy.deepcopy(results)
    wrong = model_response("ecology-priority", [])
    wrong["decision"]["evidenceRefs"] = [{"kind": "output", "id": "999"}]
    correct = model_response("ecology-priority", [])
    correct["decision"]["judgement"] = "模型重新核对真实最新统计后的判断"
    (decision, edits), requests = run([wrong, correct], workflow, stage, results)
    assert not edits and decision["judgement"] == correct["decision"]["judgement"]
    assert len(requests) == 2 and requests[1][:2] == requests[0]
    assert json.loads(requests[1][2]["content"]) == wrong
    feedback = json.loads(requests[1][3]["content"])
    assert feedback["validationError"] == "判断必须引用最近一次实际计算统计"
    assert feedback["latestStatisticsOutputIds"] == [102]
    assert results == initial_results
    assert stage["modelRequestPayload"]["actualResults"] == initial_results
    attempts = stage["modelAttempts"]
    assert [item["accepted"] for item in attempts] == [False, True]
    for index, attempt in enumerate(attempts):
        serialized = json.dumps(requests[index], ensure_ascii=False).encode("utf-8")
        assert attempt["requestSha256"] == hashlib.sha256(serialized).hexdigest()
        assert attempt["contentBytes"] == sum(
            len(m["content"].encode("utf-8")) for m in requests[index]
        )
        assert attempt["inputTokens"] == [800, 1200][index]
        assert not attempt["truncated"] and attempt["requested"]
        assert attempt["usage"]["completion_tokens"] == 200


def test_empty_edit_response_retries_then_returns_only_model_authored_edits(
    retry_model,
):
    workflow, stage, results = geology()
    edits = [{key: results[0]["rows"][1][key] for key in (*EDIT_FIELDS, "reason")}]
    (decision, proposed), requests = run(
        [model_response("geology-edit", []), model_response("geology-edit", edits)],
        workflow,
        stage,
        results,
    )
    assert decision["nextAction"] == "geology-edit" and proposed == edits
    assert "input_checksum" not in proposed[0]
    assert (
        "仍有可修复属性" in json.loads(requests[-1][-1]["content"])["validationError"]
    )


def test_second_invalid_response_stops_after_two_requests(retry_model):
    workflow, stage, results = geology()
    wrong = model_response("geology-edit", [])
    with pytest.raises(ComputeError, match="仍有可修复"):
        run([wrong, wrong], workflow, stage, results)
    assert len(stage["modelAttempts"]) == 2
    assert all(not item["accepted"] for item in stage["modelAttempts"])


def test_bad_json_retries_and_preserves_body_without_internal_thinking(retry_model):
    workflow, stage, results = ordinary_stage()
    valid = model_response("ecology-priority", [])
    (_, _), requests = run(
        ["<think>内部内容</think>not-json", valid], workflow, stage, results
    )
    assert stage["modelAttempts"][0]["response"] == "not-json"
    assert requests[1][2]["content"] == "not-json"
    assert "内部内容" not in json.dumps(stage["modelAttempts"], ensure_ascii=False)


@pytest.mark.parametrize("kind", [[], {}])
def test_malformed_reference_kind_is_a_validation_error_the_model_can_repair(
    kind, retry_model
):
    workflow, stage, results = ordinary_stage()
    bad = model_response("ecology-priority", [])
    bad["decision"]["evidenceRefs"][0]["kind"] = kind
    (decision, _), _ = run(
        [bad, model_response("ecology-priority", [])], workflow, stage, results
    )
    assert decision["evidenceRefs"][0]["kind"] == "output"
    assert stage["modelAttempts"][0]["validationError"] == "判断引用格式无效"


def test_fabricated_edits_can_be_replaced_by_genuine_model_review(retry_model):
    workflow, stage, results = geology()
    edit = {key: results[0]["rows"][1][key] for key in (*EDIT_FIELDS, "reason")}
    edit["feature_id"] = "fabricated-object"
    (decision, proposed), _ = run(
        [model_response("geology-edit", [edit]), model_response("request_review", [])],
        workflow,
        stage,
        results,
    )
    assert decision["nextAction"] == "request_review" and proposed == []
    assert "实际检查" in stage["modelAttempts"][0]["validationError"]


@pytest.mark.parametrize("action", ["ecology-priority", "request_review"])
def test_nonediting_actions_require_empty_edits_from_the_model(action, retry_model):
    workflow, stage, results = ordinary_stage()
    bad = model_response(action, [{"feature_id": "premature-edit"}])
    (decision, edits), _ = run(
        [bad, model_response(action, [])], workflow, stage, results
    )
    assert decision["nextAction"] == action and not edits
    assert "不得提前提交" in stage["modelAttempts"][0]["validationError"]


@pytest.mark.parametrize(
    "error", [ModelError("模型连接失败"), PermissionDenied("权限已撤回")]
)
def test_network_and_permission_errors_are_never_retried(error, retry_model):
    workflow, stage, results = ordinary_stage()
    with pytest.raises(type(error), match=str(error)):
        run([error], workflow, stage, results)
    assert len(stage["modelAttempts"]) == 1
    assert "response" not in stage["modelAttempts"][0]


@pytest.mark.parametrize("repair_level", [1, 2, 3, 4, 6])
def test_retry_budget_keeps_complete_payload_and_compresses_redundant_context(
    retry_model,
    repair_level,
):
    workflow, stage, results = geology()
    wrong = model_response("geology-edit", [])
    correct = model_response("geology-edit", [])
    correct["decision"]["nextAction"] = "request_review"
    (_, edits), requests = run(
        [wrong, correct],
        workflow,
        stage,
        results,
        tokens=[800, *([100000] * repair_level), 1200],
    )
    assert not edits and len(requests) == 2
    assert requests[1][1] == requests[0][1]
    if repair_level < 3:
        assert requests[1][0] == requests[0][0]
    assert len(requests[1]) == 3 and requests[1][-1]["role"] == "user"
    assert stage["modelAttempts"][-1]["repairLevel"] == repair_level
    assert stage["modelAttempts"][-1]["inputTokens"] == 1200
    assert len(stage["modelRequestPayload"]["actualResults"]) == len(results)
    workflow.max_iterations = workflow.iteration = 2
    workflow.plan["actualModelCallCount"] = 2
    with patch("apps.agent.demo_decisions.resource_context", return_value=[]):
        assert (
            decide(workflow, None, default_policy(), stage, results, lambda: None)[1]
            == edits
        )


def test_retry_byte_budget_drops_oversized_previous_response(retry_model):
    workflow, stage, results = ordinary_stage()
    wrong = model_response("ecology-priority", [])
    wrong["decision"]["judgement"] = "重复内容" * 100000
    correct = model_response("ecology-priority", [])
    (_, edits), requests = run(
        [wrong, correct], workflow, stage, results, tokens=[800, 800, 800]
    )
    assert not edits and len(requests[1]) == 3
    assert requests[1][:2] == requests[0]
    assert stage["modelAttempts"][-1]["repairLevel"] == 1
    assert (
        stage["modelAttempts"][-1]["contentBytes"]
        <= default_policy()["maxContextBytes"]
    )


def test_cancel_after_persisted_rejection_stops_before_retry(retry_model):
    workflow, stage, results = geology()
    persisted, cancelled = [], [False]

    def callback(record):
        persisted.append(copy.deepcopy(record))
        cancelled[0] = record["status"] == "rejected"

    def guard():
        if cancelled[0]:
            raise ModelError("场景分析已停止")

    with pytest.raises(ModelError, match="场景分析已停止"):
        run(
            [model_response("geology-edit", [])],
            workflow,
            stage,
            results,
            guard=guard,
            callback=callback,
        )
    assert len(stage["modelAttempts"]) == 1
    assert persisted[-1]["status"] == "rejected"


@pytest.mark.parametrize("status", ["requesting", "rejected", "accepted"])
def test_existing_attempt_audit_never_blindly_resends_after_recovery(
    status, retry_model
):
    workflow, stage, results = ordinary_stage()
    stage["modelAttempts"] = [{"attempt": 1, "status": status, "requested": True}]
    original = copy.deepcopy(stage)
    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window") as window,
        patch("apps.agent.context.count_tokens") as tokens,
        patch("apps.agent.demo_decisions.provider.stream") as stream,
        pytest.raises(ComputeError, match="本步已有模型请求记录"),
    ):
        decide(workflow, None, default_policy(), stage, results, lambda: None)
    window.assert_not_called()
    tokens.assert_not_called()
    stream.assert_not_called()
    assert stage == original


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["recover", "quota", "network"])
def test_workflow_attempts_are_durable_and_retries_consume_real_call_budget(
    mode, demo, settings
):
    from apps.agent.demo_workflow import advance_demo, prepare_demo, confirm_demo
    from apps.agent.models import AgentWorkflow
    from apps.compute.models import ComputeTask

    workflow = scenario(demo)
    prepare_demo(workflow, demo["owner"], demo["policy"])
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    if mode == "quota":
        workflow.max_iterations = 1
        workflow.save(update_fields=["max_iterations"])
    settings.AGENT_MODELS = [
        {
            "alias": "mock",
            "name": "provider集成测试",
            "model_id": "qwen-fixture",
            "base_url": "http://127.0.0.1:19100/v1",
            "agent": True,
        }
    ]
    valid = model_response("raster-ndvi", [])
    valid["decision"]["evidenceRefs"] = [
        {
            "kind": "resource",
            "id": str(demo["inputs"]["early_image"]),
        }
    ]
    requests = []
    values = iter(["invalid-json", valid])

    def durable_stream(model, messages, output, guard, **options):
        persisted = AgentWorkflow.objects.get(pk=workflow.id)
        attempts = persisted.plan["stages"][0]["modelAttempts"]
        assert persisted.plan["actualModelCallCount"] == len(requests) + 1
        assert attempts[-1]["status"] == "requesting"
        assert attempts[-1]["requested"]
        if requests:
            assert attempts[0]["status"] == "rejected"
            assert attempts[0]["response"] == "invalid-json"
            assert (
                persisted.steps.filter(
                    kind="analysis_model_attempt", status="failed"
                ).count()
                == 1
            )
        requests.append(copy.deepcopy(messages))
        if mode == "network" and len(requests) == 2:
            raise ModelError("第二次模型连接失败")
        value = next(values)
        options["on_usage"]({"prompt_tokens": 800, "completion_tokens": 100})
        return iter([value if isinstance(value, str) else json.dumps(value)])

    with (
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=800),
        patch("apps.agent.demo_decisions.provider.stream", side_effect=durable_stream),
    ):
        advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert workflow.iteration == 1
    assert workflow.plan["actualModelCallCount"] == (1 if mode == "quota" else 2)
    attempts = workflow.plan["stages"][0]["modelAttempts"]
    assert len(attempts) == 2 and not attempts[0]["accepted"]
    if mode == "recover":
        assert workflow.status == "waiting_compute" and attempts[1]["accepted"]
        assert ComputeTask.objects.count() == 1
        assert workflow.steps.filter(kind="analysis_decision").count() == 1
    else:
        assert workflow.status == "failed" and not ComputeTask.objects.exists()
        assert not workflow.steps.filter(kind="analysis_decision").exists()
        if mode == "quota":
            assert len(requests) == 1 and not attempts[1]["requested"]
            assert attempts[1]["status"] == "budget_blocked"
        else:
            assert len(requests) == 2 and attempts[1]["status"] == "requesting"
