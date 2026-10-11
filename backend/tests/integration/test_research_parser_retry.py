"""Simulated model responses verify bounded correction and durable parser evidence."""

import copy
import json
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.agent.models import AgentRun, AgentWorkflow
from apps.agent.provider import ModelError
from apps.agent.research_intents import process
from apps.agent.research_parser import validate
from apps.agent.worker import Cancelled
from apps.compute.models import ComputeTask
from tests.integration.test_chat_research_intent import catalog, parsed, run
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo  # noqa: F401

pytestmark = pytest.mark.django_db


def execute(env, item, responses, *, before_response=None, tokens=256):
    requests, events = [], []

    def stream(model, messages, limit, guard, **kwargs):
        requests.append(copy.deepcopy(messages))
        if before_response:
            before_response(len(requests))
        kwargs["on_usage"]({"prompt_tokens": 256, "completion_tokens": 120})
        response = responses[len(requests) - 1]
        if isinstance(response, Exception):
            raise response
        text = response if isinstance(response, str) else json.dumps(response)
        return iter([text])

    with (
        patch("apps.agent.research_presets.discover", return_value=catalog(env)),
        patch("apps.agent.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=tokens),
        patch("apps.agent.provider.stream", side_effect=stream) as model,
    ):
        result = process(
            item,
            env["owner"],
            env["policy"],
            lambda: None,
            lambda *args: events.append(args),
        )
    return result, requests, events, model.call_count


@pytest.mark.parametrize(
    "invalid_inputs",
    [
        {"前期影像": 1},
        {"unknown_role": 1},
        None,
        {"early_image": None},
        {"early_image": 0},
        {"early_image": True},
        {"early_image": {"id": 1}},
    ],
)
def test_input_contract_is_strict_without_role_guessing(demo, invalid_inputs):  # noqa: F811
    value = parsed(demo)
    value["inputs"] = invalid_inputs
    with pytest.raises(ValidationError):
        validate(value, catalog(demo), run(demo))


def test_translated_roles_are_reasked_with_original_catalog_and_persisted_error(
    demo,  # noqa: F811
):
    item = run(demo)
    wrong = parsed(demo)
    wrong["inputs"]["前期影像"] = wrong["inputs"].pop("early_image")
    observed = []

    def before_response(attempt):
        if attempt == 2:
            saved = AgentRun.objects.get(pk=item.pk).research_intent["_parserAudit"]
            rejected = saved["attempts"][0]
            assert rejected["status"] == "rejected"
            assert rejected["response"] == wrong
            assert "前期影像" in rejected["validationError"]
            assert "early_image" in rejected["validationError"]
            assert saved["attempts"][1]["status"] == "requesting"
            observed.append(copy.deepcopy(saved))

    result, requests, events, count = execute(
        demo, item, [wrong, parsed(demo)], before_response=before_response
    )
    assert count == 2 and len(observed) == 1 and "开始" in result
    assert requests[1][:2] == requests[0]
    original = json.loads(requests[1][1]["content"])
    assert original["authorizedCatalog"] == catalog(demo)
    assert original["userMessage"] == item.prompt
    feedback = json.loads(requests[1][-1]["content"])
    assert "前期影像" in feedback["validationError"]
    assert feedback["responseContract"]["scenarios"][0]["inputKeys"] == list(
        catalog(demo)["scenarios"][0]["inputs"]
    )
    item.refresh_from_db()
    attempts = item.research_intent["_parserAudit"]["attempts"]
    assert [a["status"] for a in attempts] == ["rejected", "accepted"]
    assert attempts[0]["response"] == wrong
    assert attempts[1]["response"] == parsed(demo)
    assert attempts[0]["requestSha256"] != attempts[1]["requestSha256"]
    assert all(a["usage"]["completion_tokens"] == 120 for a in attempts)
    assert [json.loads(e[1])["status"] for e in events if e[0] == "research_parse"] == [
        "rejected",
        "accepted",
    ]
    assert AgentWorkflow.objects.count() == 1 and not ComputeTask.objects.exists()


def test_unresolved_null_role_can_be_omitted_and_becomes_authorized_question(
    demo,  # noqa: F811
):
    item = run(demo)
    wrong = parsed(demo, "clarify")
    wrong["inputs"]["early_image"] = None
    corrected = parsed(demo, "clarify")
    corrected["inputs"].pop("early_image")
    execute(demo, item, [wrong, corrected])
    item.refresh_from_db()
    intent = item.research_intent
    assert intent["status"] == "clarifying" and "early_image" not in intent["inputs"]
    question = next(q for q in intent["questions"] if q["key"] == "early_image")
    assert question["options"] == [
        {"value": str(demo["inputs"]["early_image"]), "label": "early_image"}
    ]
    # The original model response stays separate from normalized questions.
    attempt = intent["_parserAudit"]["attempts"][1]
    assert attempt["response"]["questions"] == []
    assert attempt["validatedResponse"]["questions"] == intent["questions"]
    assert not AgentWorkflow.objects.exists() and not ComputeTask.objects.exists()


def test_unauthorized_resource_question_option_is_rejected_twice(demo):  # noqa: F811
    item = run(demo)
    wrong = parsed(demo, "clarify")
    wrong["questions"] = [
        {
            "key": "early_image",
            "label": "选择前期影像",
            "kind": "resource",
            "required": True,
            "options": [
                {"value": str(demo["inputs"]["initial_map"]), "label": "越权资料"}
            ],
        }
    ]
    with pytest.raises(ValidationError, match="授权角色"):
        execute(demo, item, [wrong, wrong])
    item.refresh_from_db()
    attempts = item.research_intent["_parserAudit"]["attempts"]
    assert len(attempts) == 2 and all(a["status"] == "rejected" for a in attempts)
    assert not AgentWorkflow.objects.exists() and not ComputeTask.objects.exists()


def test_invalid_json_is_corrected_once_and_thinking_is_not_evidence(demo):  # noqa: F811
    item = run(demo)
    corrected = "<think>内部片段不能作为证据</think>\n```json\n"
    corrected += json.dumps(parsed(demo)) + "\n```"
    _, _, _, count = execute(demo, item, ["{broken", corrected])
    item.refresh_from_db()
    audit = item.research_intent["_parserAudit"]
    assert count == 2 and audit["attempts"][0]["response"] is None
    assert audit["attempts"][0]["responseText"] == "{broken"
    assert audit["attempts"][1]["status"] == "accepted"
    assert "内部片段" not in json.dumps(audit, ensure_ascii=False)


def test_two_invalid_json_responses_stop_without_a_third_request(demo):  # noqa: F811
    item = run(demo)
    with pytest.raises(ValidationError, match="JSON"):
        execute(demo, item, ["{broken", "still broken"])
    item.refresh_from_db()
    attempts = item.research_intent["_parserAudit"]["attempts"]
    assert len(attempts) == 2
    assert [a["responseText"] for a in attempts] == ["{broken", "still broken"]
    assert all(a["status"] == "rejected" for a in attempts)
    assert not AgentWorkflow.objects.exists() and not ComputeTask.objects.exists()


@pytest.mark.parametrize(
    "failure", [ModelError("连接失败"), PermissionDenied(), Cancelled()]
)
def test_transport_permission_and_cancel_errors_never_retry(demo, failure):  # noqa: F811
    item = run(demo)
    with pytest.raises(type(failure)):
        execute(demo, item, [failure])
    item.refresh_from_db()
    attempts = item.research_intent["_parserAudit"]["attempts"]
    assert len(attempts) == 1 and attempts[0]["status"] == "failed"
    assert attempts[0]["executionError"] == type(failure).__name__
    assert not AgentWorkflow.objects.exists() and not ComputeTask.objects.exists()


def test_network_failure_after_rejection_keeps_both_attempts(demo):  # noqa: F811
    item = run(demo)
    wrong = parsed(demo)
    wrong["inputs"] = None
    with pytest.raises(ModelError):
        execute(demo, item, [wrong, ModelError("连接失败")])
    item.refresh_from_db()
    attempts = item.research_intent["_parserAudit"]["attempts"]
    assert [a["status"] for a in attempts] == ["rejected", "failed"]
    assert attempts[0]["response"] == wrong
    assert not AgentWorkflow.objects.exists() and not ComputeTask.objects.exists()


def test_conflicting_user_bands_generate_one_question_without_revalidation(
    demo,  # noqa: F811
):
    item = run(demo, "分析两期植被变化，red=1 red=2 nir=2")
    execute(demo, item, [parsed(demo)])
    item.refresh_from_db()
    assert item.research_intent["status"] == "clarifying"
    assert [q["key"] for q in item.research_intent["questions"]] == ["red"]
    attempts = item.research_intent["_parserAudit"]["attempts"]
    assert len(attempts) == 1 and attempts[0]["response"]["questions"] == []
    assert attempts[0]["validatedResponse"]["questions"][0]["key"] == "red"


def test_invalid_date_is_reported_to_model_for_one_correction(demo):  # noqa: F811
    item = run(demo)
    wrong = parsed(demo)
    wrong["parameters"]["early_date"] = "2024/06/01"
    _, requests, _, count = execute(demo, item, [wrong, parsed(demo)])
    feedback = json.loads(requests[1][-1]["content"])
    assert count == 2 and "early_date" in feedback["validationError"]


@pytest.mark.parametrize("bad_action", [[], {}, None])
def test_invalid_action_type_is_rejected_with_bounded_correction(
    demo,  # noqa: F811
    bad_action,
):
    item = run(demo)
    wrong = parsed(demo)
    wrong["action"] = bad_action
    _, _, _, count = execute(demo, item, [wrong, parsed(demo)])
    assert count == 2


@pytest.mark.parametrize("bad_kind", [[], {}, None])
def test_invalid_question_kind_is_a_validation_error(demo, bad_kind):  # noqa: F811
    wrong = parsed(demo, "clarify")
    wrong["questions"] = [
        {
            "key": "red",
            "label": "红光",
            "kind": bad_kind,
            "required": True,
            "options": [],
        }
    ]
    with pytest.raises(ValidationError, match="问题格式"):
        validate(wrong, catalog(demo), run(demo))


def test_clarification_with_invalid_action_type_is_corrected_once(demo):  # noqa: F811
    first = run(demo)
    question = parsed(demo, "clarify")
    question["parameters"].pop("nir")
    execute(demo, first, [question])
    answer = run(demo, "近红外是2，开始执行", conversation=first.conversation)
    wrong = parsed(demo)
    wrong["action"] = []
    _, _, _, count = execute(demo, answer, [wrong, parsed(demo)])
    answer.refresh_from_db()
    assert count == 2 and answer.research_intent["originRunId"] == first.id
    assert AgentWorkflow.objects.count() == 1


def test_extremely_large_number_is_rejected_without_overflow(demo):  # noqa: F811
    choices = catalog(demo)
    choices["scenarios"][0]["parameterSpecs"].append(
        {"key": "decline_threshold", "label": "下降阈值", "type": "number"}
    )
    wrong = parsed(demo)
    wrong["parameters"]["decline_threshold"] = 10**400
    with pytest.raises(ValidationError, match="参数类型"):
        validate(wrong, choices, run(demo))


def test_second_attempt_rechecks_budget_without_truncating_catalog(demo):  # noqa: F811
    item = run(demo)
    responses = []

    def stream(*args, **kwargs):
        responses.append(args)
        return iter(["{broken"])

    with (
        patch("apps.agent.research_presets.discover", return_value=catalog(demo)),
        patch("apps.agent.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", side_effect=[256, 100000]),
        patch("apps.agent.provider.stream", side_effect=stream),
        pytest.raises(ModelError, match="输入需要"),
    ):
        process(item, demo["owner"], demo["policy"], lambda: None, lambda *args: None)
    item.refresh_from_db()
    assert len(responses) == 1
    assert item.research_intent["_parserAudit"]["attempts"][0]["status"] == "rejected"
    assert not AgentWorkflow.objects.exists() and not ComputeTask.objects.exists()
