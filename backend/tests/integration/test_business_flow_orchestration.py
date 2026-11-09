"""The ordinary agent hands off a real durable flow, never a decorative card."""

import json
from uuid import uuid4
from unittest.mock import patch

from django.core.exceptions import ValidationError
import pytest

from apps.agent import worker
from apps.agent.models import AgentRun, AgentWorkflow
from apps.agent.interactions import resume_compute
from apps.agent.tools import execute
from apps.business_flows import catalog, runtime, engine
from apps.business_flows.builtins import source_summary_definition
from apps.business_flows.state import state
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent  # noqa: F401

# ruff: noqa: F811
pytestmark = pytest.mark.efficiency


def definition(env, *, kind="agent", human=False):
    spec = source_summary_definition()
    spec["nodes"] = spec["nodes"][:1]
    spec["nodes"][0]["kind"] = kind
    spec["nodes"][0]["review"].update(human=human, maxRevisions=1 if human else 0)
    with project_scope(env["scope"]):
        return catalog.register_flow(
            env["admin"],
            {
                "code": "flow-" + uuid4().hex[:8],
                "name": "规范化资料流程",
                "description": "按定义整理实际资料",
                "definition": spec,
            },
        )


def test_ordinary_agent_can_discover_and_start_flow_without_a_second_user_turn(
    setup_agent, monkeypatch
):
    env = setup_agent
    _, version = definition(env)
    calls = []

    def response(model, messages, *args, **kwargs):
        calls.append(messages)
        if len(calls) == 1:
            yield json.dumps({"action": "list_business_flows", "arguments": {}})
        else:
            yield json.dumps(
                {
                    "action": "start_business_flow",
                    "arguments": {
                        "versionId": version.pk,
                        "inputs": {"source": env["resource"].pk},
                    },
                }
            )

    monkeypatch.setattr(worker, "stream", response)
    monkeypatch.setattr(worker, "model_window", lambda model: 32768)
    monkeypatch.setattr(worker, "prepare_context", lambda *args: (1, False))
    with project_scope(env["scope"]):
        run = AgentRun.objects.create(
            owner=env["user"],
            conversation=env["conversation"],
            model="mock",
            prompt="请启动业务流梳理这份资料",
            status="running",
            idempotency_key=uuid4().hex,
            resource_ids=[env["resource"].pk],
            knowledge_selection={"_contextRunIds": []},
        )
    worker.run_task(run.pk)
    run.refresh_from_db()
    assert len(calls) == 2
    assert run.status == "waiting_compute", run.detail
    assert run.research_workflow_id
    assert run.execution_state["phase"] == "business_flow"
    workflow = AgentWorkflow.objects.get(pk=run.research_workflow_id)
    assert workflow.parameters["_businessFlow"]["runId"] == run.pk
    with project_scope(env["scope"]):
        resume_compute()
    run.refresh_from_db()
    assert run.status == "waiting_compute"
    assert not worker.claim()


def test_flow_list_pages_without_duplicate_definitions_or_full_instructions(
    setup_agent,
):
    env = setup_agent
    for _ in range(11):
        definition(env)
    with project_scope(env["scope"]):
        run = AgentRun.objects.create(
            owner=env["user"],
            conversation=env["conversation"],
            model="mock",
            prompt="有哪些业务流",
            status="running",
            idempotency_key=uuid4().hex,
        )
        one, _ = execute(run, "list_business_flows", {"limit": 8})
        two, _ = execute(
            run, "list_business_flows", {"limit": 8, "offset": one["nextOffset"]}
        )
        assert len(one["items"]) == 8 and len(two["items"]) == 3
        assert not {item["id"] for item in one["items"]} & {
            item["id"] for item in two["items"]
        }
        assert all(
            "instruction" not in node for item in one["items"] for node in item["nodes"]
        )
        with pytest.raises(ValidationError):
            execute(run, "list_business_flows", {"limit": True})


@pytest.mark.parametrize("kind", ["human", "result"])
def test_returned_human_or_summary_node_uses_real_executor_revision_instead_of_replaying(
    setup_agent, kind
):
    env = setup_agent
    _, version = definition(env, kind=kind, human=True)
    with project_scope(env["scope"]):
        workflow = runtime.start_flow(
            env["user"],
            version,
            {
                "model": "mock",
                "goal": "整理可用字段",
                "inputs": {"source": env["resource"].pk},
                "idempotencyKey": uuid4().hex,
            },
        )
        engine.advance(workflow.pk)
        workflow.refresh_from_db()
        assert workflow.status == "waiting_approval"
        runtime.decide_flow(
            env["user"],
            workflow,
            {
                "nodeId": "summarize",
                "revision": state(workflow)["revision"],
                "decision": "request_changes",
                "feedback": "请清楚说明只读了有界样本。",
                "idempotencyKey": uuid4().hex,
            },
        )
        with patch(
            "apps.agent.business_flow_execution.execute_node",
            return_value={
                "summary": "当前仅核对资料元信息及有界样本。",
                "findings": [],
                "limitations": ["没有逐项检查全部记录"],
                "evidenceIds": [f"resource-{env['resource'].pk}"],
            },
        ) as revise:
            engine.advance(workflow.pk)
        workflow.refresh_from_db()
        assert revise.call_count == 1
        assert (
            revise.call_args.kwargs["feedback"]["repairInstructions"]
            == "请清楚说明只读了有界样本。"
        )
        assert workflow.status == "waiting_approval"
        assert state(workflow)["nodes"]["summarize"]["human"]["status"] == "pending"
