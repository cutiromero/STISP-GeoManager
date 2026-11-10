"""辅助调用使用真实请求入口和同一保守分词器，不连接模型服务。"""

import json
from uuid import uuid4

import pytest

from apps.agent import context, conversation_titles, generic_mapping, provider
from apps.agent.config import registry
from apps.agent.models import AgentPolicy, AgentRun, Conversation
from apps.agent.policy import default_policy
from apps.agent.research_parser import interpret, validate
from tests.integration.test_logic_flow_budget_audit import (
    OUTPUT,
    OUTPUT_TOKENS,
    SCALES,
    WINDOWS,
    conservative_tokens,
)
from tests.integration.test_workflow_profile_models import infer_roles

pytestmark = [pytest.mark.django_db, pytest.mark.efficiency]
pytest_plugins = ["tests.integration.test_workflow_profile_models"]


@pytest.mark.parametrize("window", WINDOWS)
@pytest.mark.parametrize("scale", SCALES)
def test_auxiliary_calls_share_window_budget(profiles, monkeypatch, scale, window):
    env = profiles
    policy = {
        **default_policy(),
        "operatorEnabled": True,
        "maxOutputTokens": OUTPUT_TOKENS,
    }
    AgentPolicy.objects.update(value=policy)
    env["project"].code = "02"
    env["project"].save(update_fields=["code"])
    profile = {
        **env["upload"].profile,
        "featureCount": env["upload"].profile["featureCount"] * scale,
    }
    env["upload"].profile = profile
    env["upload"].save(update_fields=["profile"])
    monkeypatch.setattr(provider, "model_window", lambda model: window)
    monkeypatch.setattr(provider, "count_tokens", conservative_tokens)
    monkeypatch.setattr(context, "count_tokens", conservative_tokens)
    requests = []
    active = {"point": "roles"}

    def record(model, messages, maximum):
        tokens = conservative_tokens(model, messages)
        budget = min(policy["maxContextTokens"], window - maximum - 256)
        assert tokens <= budget
        requests.append(
            {
                "point": active["point"],
                "tokens": tokens,
                "budget": budget,
                "level": 0,
                "projectionRecipe": 0,
            }
        )

    def stream(model, messages, maximum, guard, **options):
        guard()
        record(model, messages, maximum)
        payload = json.loads(messages[1]["content"])
        if active["point"] == "roles":
            answer = {
                "items": [
                    {
                        "uploadId": row["uploadId"],
                        "role": "lithology",
                        "reason": "面数据与地层名称示例",
                    }
                    for row in payload["items"]
                ]
            }
        elif active["point"] == "inputs":
            answer = {
                "roles": {
                    "lithology": {"name": {"field": "DCMC", "reason": "真实字段及示例"}}
                }
            }
        else:
            answer = {
                "action": "clarify",
                "scenario": "geology_generic",
                "goal": "检查地质资料",
                "message": "确认目标后再执行，不自动批准资料或对象",
                "inputs": {},
                "parameters": {},
                "questions": [
                    {
                        "key": "goal",
                        "label": "请确认检查范围",
                        "kind": "text",
                        "required": True,
                        "options": [],
                    }
                ],
            }
        yield json.dumps(answer, ensure_ascii=False)

    monkeypatch.setattr(provider, "stream", stream)
    assert infer_roles(env)["source"] == "model"
    active["point"] = "inputs"
    assert (
        generic_mapping.model_targets(env["workflow"], policy, env["roles"])[
            "lithology"
        ]["name"]["field"]
        == "DCMC"
    )
    conversation = Conversation.objects.create(owner=env["owner"], mode="agent")
    run = AgentRun.objects.create(
        owner=env["owner"],
        conversation=conversation,
        model="qwen",
        status="succeeded",
        prompt="核对地质资料并确认检查范围。" * scale,
        idempotency_key=uuid4().hex,
        resource_ids=[env["upload"].resource_id],
        research_intent={"_demoScenario": "geology_generic"},
    )
    choices = {
        "scenarios": [
            {
                "scenario": "geology_generic",
                "inputs": {},
                "parameterSpecs": [],
                "algorithms": [],
            }
        ]
    }
    active["point"] = "research-parser"
    answer, audit = interpret(
        run,
        env["owner"],
        policy,
        choices,
        None,
        None,
        lambda: None,
        lambda *args: None,
        lambda audit: None,
        validator=lambda value: validate(value, choices, run),
    )
    assert (
        answer["action"] == "clarify" and audit["attempts"][-1]["status"] == "accepted"
    )
    active["point"] = "conversation-title"

    def title(model, path, body, **options):
        record(model, body["messages"], body["max_tokens"])
        return {
            "choices": [{"message": {"content": json.dumps({"title": "地质资料检查"})}}]
        }

    monkeypatch.setattr(provider, "model_request", title)
    assert conversation_titles.generate_conversation_title(run.id)
    assert registry()[run.model].alias == "qwen"
    assert {row["point"] for row in requests} == {
        "roles",
        "inputs",
        "research-parser",
        "conversation-title",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / f"aux-{scale}x-{window}.json").write_text(
        json.dumps(
            {"scale": scale, "window": window, "requests": requests, "waits": []},
            ensure_ascii=False,
            indent=2,
        )
    )
    for row in requests:
        print(
            f"{scale}x | {window} | {row['point']} | {row['tokens']} | {row['budget']} | {row['level']} | 否"
        )
