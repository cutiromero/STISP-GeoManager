"""Task budget selection, continued admission and public recovery information."""

from types import SimpleNamespace
from uuid import uuid4
import json
from copy import deepcopy

from django.core.exceptions import ValidationError
from django.core.exceptions import PermissionDenied
import pytest

from apps.agent.models import AgentPolicy
from apps.agent.policy import default_policy
from apps.agent.workflow_model_policy import workflow_model_policy
from apps.business_flows import runtime, legacy
from apps.business_flows.builtins import geology_definition
from apps.business_flows.state import state, parent_run
from apps.compute.packages import ComputeError
from apps.projects.context import project_scope
from tests.integration.test_business_flow_runtime import flows, start  # noqa: F401
from tests.integration.test_agent import setup_agent  # noqa: F401
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_business_flow_operator_runtime import operators  # noqa: F401

# ruff: noqa: F811
pytestmark = pytest.mark.efficiency


def configure(monkeypatch, **changes):
    policy = {**default_policy(), **changes}
    AgentPolicy.objects.update_or_create(pk=1, defaults={"value": policy})
    monkeypatch.setattr(
        "apps.agent.policy.visible_models",
        lambda *args: [{"alias": "mock", "contextWindowTokens": 262144}],
    )
    return policy


def operator_definition(env, count=1):
    from apps.business_flows.builtins import source_summary_definition

    definition = source_summary_definition(main_agent=True)
    finish = deepcopy(definition["nodes"][-1])
    nodes = []
    for index in range(count):
        identity = f"calculate{index}"
        nodes.append(
            {
                "id": identity,
                "kind": "operator",
                "title": "统计实际资料",
                "description": "使用既有配置统计",
                "dependsOn": [nodes[-1]["id"]] if nodes else [],
                "dataRoles": ["source"],
                "instruction": "依据真实资料执行统计",
                "algorithmVersionId": env["version"].pk,
                "parameters": deepcopy(env["body"]["parameters"]),
                "inputBindings": {
                    env["version"].manifest["inputs"][0]["key"]: {"role": "source"}
                },
                "review": {"ai": False, "human": False, "maxRevisions": 0},
            }
        )
    finish["dependsOn"] = [nodes[-1]["id"]]
    definition["nodes"] = [*nodes, finish]
    return definition


def test_model_receives_the_configured_operator_version_parameters_and_bindings(
    operators, monkeypatch
):
    from apps.agent import provider
    from apps.business_flows import catalog, engine

    env = operators
    configure(monkeypatch, operatorEnabled=True)
    packets = []
    monkeypatch.setattr(provider, "model_window", lambda *args: 32768)
    monkeypatch.setattr(provider, "count_tokens", lambda *args, **kwargs: 1000)

    def stream(model, messages, maximum, guard, **kwargs):
        guard()
        packet = json.loads(messages[1]["content"])
        packets.append(packet)
        if packet["nodeContext"]["task"]["phase"] == "select_node":
            yield json.dumps(
                {"action": "start_node", "arguments": {"nodeId": "calculate0"}}
            )
        else:
            yield json.dumps(
                {"action": "ask_user", "arguments": {"question": "已读取节点配置"}}
            )

    monkeypatch.setattr(provider, "stream", stream)
    with project_scope(env["scope"]):
        _, version = catalog.register_flow(
            env["admin"],
            {
                "code": "defaults-" + uuid4().hex[:8],
                "name": "默认配置传输",
                "definition": operator_definition(env),
            },
        )
        workflow = runtime.start_flow(
            env["owner"],
            version,
            {
                "model": "mock",
                "goal": "统计实际资料",
                "inputs": {"source": env["resource"].pk},
                "idempotencyKey": uuid4().hex,
            },
        )
    engine.advance(workflow.pk)
    engine.advance(workflow.pk)
    defaults = packets[-1]["nodeContext"]["nodeDefaults"]
    assert defaults["versionId"] == env["version"].pk
    assert defaults["configuredParameters"] == env["body"]["parameters"]
    assert defaults["inputBindings"][env["version"].manifest["inputs"][0]["key"]] == {
        "role": "source"
    }


def test_known_insufficient_operator_budget_rejects_before_creating_a_workflow(
    operators, monkeypatch
):
    from apps.agent.models import AgentWorkflow
    from apps.business_flows import catalog

    env = operators
    configure(monkeypatch, operatorEnabled=True, maxOperatorSteps=1)
    with project_scope(env["scope"]):
        _, version = catalog.register_flow(
            env["admin"],
            {
                "code": "quota-" + uuid4().hex[:8],
                "name": "调用预算预检",
                "definition": operator_definition(env, 2),
            },
        )
        with pytest.raises(ComputeError, match="至少需要2次算子调用"):
            runtime.start_flow(
                env["owner"],
                version,
                {
                    "model": "mock",
                    "goal": "统计两次",
                    "inputs": {"source": env["resource"].pk},
                    "idempotencyKey": uuid4().hex,
                },
            )
        assert not AgentWorkflow._base_manager.filter(owner=env["owner"]).exists()


def test_launch_budget_is_frozen_and_shared_by_execution_and_review(
    flows, monkeypatch, settings
):
    settings.AGENT_MODELS = [{**row, "qwen": True} for row in settings.AGENT_MODELS]
    policy = configure(monkeypatch, taskBudgetsEnabled=True)
    _, version = flows["create"]()
    workflow, value = start(
        flows,
        version,
        budgetProfile="reasoning",
        maxOutputTokens=24000,
        reasoningEffort="medium",
    )
    with project_scope(flows["scope"]):
        run = parent_run(workflow)
        assert run.budget_snapshot["maxOutputTokens"] == 24000
        assert run.budget_profile == "reasoning"
        assert (
            workflow_model_policy(workflow, flows["user"], policy)["maxOutputTokens"]
            == 24000
        )
        assert run.reasoning_effort == "medium"
        assert runtime.start_flow(flows["user"], version, value).pk == workflow.pk
        with pytest.raises(ComputeError, match="幂等"):
            runtime.start_flow(
                flows["user"], version, {**value, "maxOutputTokens": 20000}
            )


@pytest.mark.parametrize(
    "changes",
    [
        {"maxOutputTokens": 32769},
        {"maxOutputTokens": True},
        {"maxOutputTokens": None},
        {"budgetProfile": False},
        {"budgetProfile": "unknown"},
    ],
)
def test_launch_budget_rejects_invalid_or_unauthorized_values(
    flows, monkeypatch, changes
):
    configure(monkeypatch, taskBudgetsEnabled=True)
    _, version = flows["create"]()
    with pytest.raises(ValidationError):
        start(flows, version, **changes)


def test_disabled_task_budgets_are_not_bypassed_by_flow_launch(flows, monkeypatch):
    configure(monkeypatch, taskBudgetsEnabled=False)
    _, version = flows["create"]()
    with pytest.raises(ValidationError, match="尚未开启"):
        start(flows, version, budgetProfile="reasoning")


def test_replacing_current_input_does_not_drop_acl_checks_for_prior_task_sources(flows):
    from apps.catalog.models import DataResource
    from apps.business_flows.engine import live_guard

    _, version = flows["create"]()
    workflow, _ = start(flows, version)
    original = flows["resource"]
    with project_scope(flows["scope"]):
        replacement = DataResource.objects.create(
            name="替换后的资料",
            data_type=original.data_type,
            source=deepcopy(original.source),
            maintainer=flows["user"],
            owner_only=True,
        )
        workflow.plan["inputs"] = {"source": replacement.pk}
        workflow.parameters["_businessFlow"]["inputVersions"] = {
            "source": {
                "id": replacement.pk,
                "name": replacement.name,
                "dataType": replacement.data_type,
                "updatedAt": replacement.updated_at.isoformat(),
            }
        }
        workflow.resource_ids = [original.pk, replacement.pk]
        workflow.save(update_fields=["plan", "parameters", "resource_ids"])
        DataResource.objects.filter(pk=original.pk).update(
            owner_only=True, maintainer=flows["other"]
        )
        with pytest.raises(PermissionDenied, match="撤权"):
            runtime.authorize(flows["user"], workflow)
        with pytest.raises(PermissionDenied, match="撤权"):
            live_guard(workflow)()


def test_http_start_accepts_and_preserves_the_frontend_budget_fields(
    flows, monkeypatch
):
    configure(monkeypatch, taskBudgetsEnabled=True)
    flow, version = flows["create"]()
    body = {
        "model": "mock",
        "goal": "核对实际资料",
        "inputs": {"source": flows["resource"].pk},
        "parameters": {},
        "versionId": version.pk,
        "idempotencyKey": uuid4().hex,
        "budgetProfile": "reasoning",
        "maxOutputTokens": 24000,
    }
    response = flows["client"].post(
        f"/api/business-flows/{flow.pk}/start/",
        json.dumps(body),
        content_type="application/json",
        **flows["header"],
    )
    assert response.status_code == 202, response.content
    payload = response.json()
    assert payload["versionId"] == version.pk and payload["flowId"] == flow.pk
    assert len(payload["nodes"]) == len(version.definition["nodes"])
    from apps.agent.models import AgentRun

    assert (
        AgentRun.objects.get(pk=payload["runId"]).budget_snapshot["maxOutputTokens"]
        == 24000
    )
    detail = flows["client"].get(
        f"/api/business-flows/runs/{payload['id']}/", **flows["header"]
    )
    assert detail.status_code == 200 and detail.json()["id"] == payload["id"]


def test_task_quota_can_continue_after_live_allowance_grows_without_reset(
    flows, monkeypatch
):
    policy = configure(monkeypatch, maxSteps=2)
    _, version = flows["create"](one=True)
    workflow, _ = start(flows, version)
    workflow.current_step, workflow.status = "summarize", "waiting_approval"
    values = state(workflow)
    values["requestedIds"] = [str(i) for i in range(4)]
    item = values["nodes"]["summarize"]
    item.update(
        status="waiting_context",
        attempt=1,
        contextRecovery={
            "nodeId": "summarize",
            "level": 0,
            "kind": "model_call_limit",
            "budgetScope": "task",
            "evidence": [],
        },
    )
    workflow.save(update_fields=["plan", "status", "current_step"])
    decision = {
        "nodeId": "summarize",
        "revision": values["revision"],
        "decision": "retry_context",
        "idempotencyKey": uuid4().hex,
    }
    with project_scope(flows["scope"]):
        with pytest.raises(ComputeError, match="尚未增加"):
            runtime.decide_flow(flows["user"], workflow, decision)
        AgentPolicy.objects.update(value={**policy, "maxSteps": 8})
        resumed = runtime.decide_flow(flows["user"], workflow, decision)
        assert resumed.max_iterations == 16
        assert state(resumed)["requestedIds"] == [str(i) for i in range(4)]
        assert state(resumed)["nodes"]["summarize"]["human"]["status"] != "approved"
        again = runtime.decide_flow(flows["user"], resumed, decision)
        assert len(state(again)["budgetAdjustments"]) == 1


def test_budget_selection_accounts_for_a_smaller_independent_reviewer(
    flows, monkeypatch, settings
):
    settings.AGENT_MODELS = [
        *settings.AGENT_MODELS,
        {
            **settings.AGENT_MODELS[0],
            "alias": "small-reviewer",
            "context_window_tokens": 16384,
        },
    ]
    configure(monkeypatch, taskBudgetsEnabled=True)
    monkeypatch.setattr(
        "apps.agent.policy.visible_models",
        lambda *args: [
            {"alias": "mock", "contextWindowTokens": 262144},
            {"alias": "small-reviewer", "contextWindowTokens": 16384},
        ],
    )
    _, version = flows["create"](ai=True)
    workflow, _ = start(
        flows, version, budgetProfile="reasoning", reviewerModel="small-reviewer"
    )
    with project_scope(flows["scope"]):
        assert parent_run(workflow).budget_snapshot["maxOutputTokens"] == 8192
    with pytest.raises(ValidationError, match="允许范围"):
        start(
            flows,
            version,
            budgetProfile="reasoning",
            reviewerModel="small-reviewer",
            maxOutputTokens=24000,
        )


def test_exhaustion_diagnostic_counts_main_tools_and_reviews_together(
    flows, monkeypatch
):
    from apps.agent.demo_workflow import _exhaust_model_budget

    configure(monkeypatch)
    _, version = flows["create"](one=True)
    workflow, _ = start(flows, version)
    stage = {"name": "summarize", "identifier": "analysis", "status": "pending"}
    workflow.plan.update(actualModelCallCount=3, stages=[stage])
    state(workflow)["requestedIds"] = ["review-call", "tool-call"]
    with project_scope(flows["scope"]):
        _exhaust_model_budget(workflow, stage, 2)
    assert stage["contextBudgetReview"]["usedRequests"] == 5


@pytest.mark.parametrize("failure", ["syntax", "unexpected_field", "unseen_reference"])
def test_invalid_review_can_resume_without_reexecuting_the_main_agent_node(
    flows, monkeypatch, failure
):
    from apps.agent import provider
    from apps.business_flows import catalog, engine
    from apps.business_flows.builtins import source_summary_definition
    from tests.integration.test_business_flow_main_agent import install_model

    calls = install_model(monkeypatch)
    normal = provider.stream
    failed_reviews = 0
    work_calls = 0

    def stream(model, messages, maximum, guard, **options):
        nonlocal failed_reviews, work_calls
        packet = json.loads(messages[1]["content"])
        if packet.get("nodeContext", {}).get("task", {}).get("phase") == "work":
            work_calls += 1
        if "requiredEvidenceIds" in packet and failed_reviews < 2:
            failed_reviews += 1
            guard()
            if failure == "syntax":
                yield "invalid-json"
            else:
                verdict = {
                    "decision": "accept",
                    "reason": "核对结果",
                    "evidenceIds": [row["id"] for row in packet["evidence"]],
                }
                if failure == "unexpected_field":
                    verdict["humanApproved"] = True
                else:
                    verdict["evidenceIds"] = ["unseen-source"]
                yield json.dumps(verdict)
        else:
            yield from normal(model, messages, maximum, guard, **options)

    monkeypatch.setattr(provider, "stream", stream)
    definition = source_summary_definition(main_agent=True)
    definition["nodes"] = definition["nodes"][:1]
    definition["nodes"][0]["review"].update(ai=True, maxRevisions=1)
    with project_scope(flows["scope"]):
        _, version = catalog.register_flow(
            flows["admin"],
            {
                "code": "protocol-" + uuid4().hex[:8],
                "name": "审核响应恢复",
                "definition": definition,
            },
        )
    workflow, _ = start(flows, version)
    for _ in range(5):
        engine.advance(workflow.pk)
        workflow.refresh_from_db()
        if workflow.status == "waiting_approval":
            break
    item = state(workflow)["nodes"]["summarize"]
    assert workflow.status == "waiting_approval", workflow.detail
    assert item["contextRecovery"]["kind"] == "model_protocol_error"
    assert item["executor"]["status"] == "succeeded"
    assert item["human"]["status"] != "approved"
    used = len(state(workflow)["requestedIds"])
    with project_scope(flows["scope"]):
        workflow = runtime.decide_flow(
            flows["user"],
            workflow,
            {
                "nodeId": "summarize",
                "decision": "retry_context",
                "revision": state(workflow)["revision"],
                "idempotencyKey": uuid4().hex,
            },
        )
    for _ in range(5):
        engine.advance(workflow.pk)
        workflow.refresh_from_db()
        if workflow.status == "succeeded":
            break
    assert workflow.status == "succeeded", workflow.detail
    assert work_calls == 1 and calls
    assert len(state(workflow)["requestedIds"]) > used


@pytest.mark.parametrize("placement", ["stages", "finalStage"])
def test_legacy_input_budget_recovery_has_a_complete_public_shape(placement):
    workflow = SimpleNamespace(
        workflow_type="geology_generic",
        model="mock",
        status="waiting_approval",
        current_step="final_analysis",
        parameters={"_businessFlow": {"definitionSnapshot": geology_definition()}},
        plan={"stages": []},
    )
    final_stage = {
        "name": "final_analysis",
        "identifier": "finish",
        "contextBudgetReview": {"reason": "必要事实超出窗口", "beforeTokens": None},
    }
    if placement == "stages":
        workflow.plan["stages"].append(final_stage)
    else:
        workflow.plan["finalStage"] = final_stage
    recovery = legacy.projected_state(workflow)["nodes"]["finish"]["contextRecovery"]
    assert (
        recovery["nodeId"] == "finish"
        and recovery["level"] == 0
        and recovery["evidence"] == []
    )
    assert "beforeTokens" not in recovery
