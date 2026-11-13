"""Execution errors retain actionable diagnostics and the exact checkpoint."""

# ruff: noqa: F811
from copy import deepcopy
import json
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from apps.agent import provider
from apps.business_flows import catalog, engine, runtime, input_preparation
from apps.business_flows.builtins import source_summary_definition
from apps.business_flows.execution_session import session
from apps.business_flows.state import state
from apps.compute.packages import ComputeError
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent  # noqa: F401
from tests.integration.test_business_flow_runtime import flows  # noqa: F401
from tests.integration.test_business_flow_main_agent import install_model
from tests.integration.test_business_flow_legacy import legacy_flow  # noqa: F401

pytestmark = pytest.mark.efficiency


def start(env):
    definition = source_summary_definition(main_agent=True)
    definition["nodes"] = definition["nodes"][:1]
    definition["nodes"][0]["review"].update(ai=False, human=False)
    _, version = catalog.register_flow(
        env["admin"],
        {
            "code": "handoff-" + uuid4().hex[:8],
            "name": "执行错误交接",
            "definition": definition,
        },
    )
    return runtime.start_flow(
        env["user"],
        version,
        {
            "model": "mock",
            "goal": "检查真实输入",
            "inputs": {"source": env["resource"].pk},
            "idempotencyKey": uuid4().hex,
        },
    )


def install_diagnosis(monkeypatch):
    calls = install_model(monkeypatch)
    normal = provider.stream
    diagnostics = []

    def stream(model, messages, maximum, guard, **options):
        packet = json.loads(messages[1]["content"])
        if packet.get("nodeContext", {}).get("purpose") == "failure_diagnosis":
            diagnostics.append(packet)
            guard()
            yield json.dumps(
                {
                    "analysis": "已确认缺少category映射，现有记录没有该类别对应。",
                    "suggestions": [
                        "请补充category对应的真实类别名称，修复映射后继续。"
                    ],
                },
                ensure_ascii=False,
            )
            return
        yield from normal(model, messages, maximum, guard, **options)

    monkeypatch.setattr(provider, "stream", stream)
    return calls, diagnostics


def retry(env, workflow):
    return runtime.decide_flow(
        env["user"],
        workflow,
        {
            "nodeId": "summarize",
            "decision": "retry_context",
            "feedback": "已核实并补全category映射，请按真实资料继续。",
            "revision": state(workflow)["revision"],
            "idempotencyKey": uuid4().hex,
        },
    )


@pytest.mark.parametrize(
    "error",
    [
        ComputeError("category缺少映射，期望真实名称，实际为空"),
        ValidationError("category类型无效"),
        RuntimeError("private service secret must not be returned"),
    ],
)
def test_all_execution_exceptions_wait_with_diagnosis_and_resume_original_task(
    flows, monkeypatch, error
):
    env = flows
    _, diagnoses = install_diagnosis(monkeypatch)
    original = input_preparation.advance_inputs
    failures = []

    def fail_once(*args, **kwargs):
        if not failures:
            failures.append(True)
            raise error
        return original(*args, **kwargs)

    monkeypatch.setattr(input_preparation, "advance_inputs", fail_once)
    with project_scope(env["scope"]):
        workflow = start(env)
        identity = session(workflow)["id"]
        snapshot = deepcopy(workflow.parameters["_businessFlow"]["definitionSnapshot"])
        engine.advance(workflow.pk)
        workflow.refresh_from_db()
        assert workflow.status == "waiting_approval"
        item = state(workflow)["nodes"]["summarize"]
        recovery = item["contextRecovery"]
        diagnostic = recovery["diagnostic"]
        assert diagnostic["analysisStatus"] == "completed"
        assert "summarize" in diagnostic["location"]
        assert "category" in diagnostic["analysis"]
        assert diagnostic["references"] == ["workflow:" + str(workflow.pk)]
        assert item["human"]["status"] == "not_required"
        assert "private service secret" not in json.dumps(recovery)
        assert len(diagnoses) == 1
        assert diagnoses[0]["executionSession"]["id"] == identity
        before = len(state(workflow)["requestedIds"])
        engine.advance(workflow.pk)
        assert len(diagnoses) == 1  # No automatic spin during human handoff.
        workflow = retry(env, workflow)
        assert len(state(workflow)["requestedIds"]) == before
        for _ in range(12):
            engine.advance(workflow.pk)
            workflow.refresh_from_db()
            if workflow.status == "succeeded":
                break
        assert workflow.status == "succeeded", workflow.detail
        assert session(workflow)["id"] == identity
        assert workflow.parameters["_businessFlow"]["definitionSnapshot"] == snapshot
        assert workflow.operator_steps == 0


def test_diagnosis_failure_never_hides_original_error_or_prevents_human_recovery(
    flows, monkeypatch
):
    install_diagnosis(monkeypatch)

    def offline(*args, **kwargs):
        raise provider.ModelError("服务暂时不可用")
        yield  # pragma: no cover

    monkeypatch.setattr(provider, "stream", offline)
    monkeypatch.setattr(
        input_preparation,
        "advance_inputs",
        lambda *a, **k: (_ for _ in ()).throw(ComputeError("category缺少真实名称")),
    )
    with project_scope(flows["scope"]):
        workflow = start(flows)
        engine.advance(workflow.pk)
        workflow.refresh_from_db()
        recovery = state(workflow)["nodes"]["summarize"]["contextRecovery"]
        assert recovery["diagnostic"]["analysisStatus"] == "unavailable"
        assert "category缺少真实名称" in recovery["diagnostic"]["facts"][0]
        assert "AI诊断未完成" in recovery["diagnostic"]["analysis"]
        assert retry(flows, workflow).status == "queued"


def test_professional_handoff_restores_phase_and_preserves_accepted_scientific_decision(
    legacy_flow, monkeypatch
):
    from apps.business_flows.failure_handoff import handoff_exception
    from apps.business_flows import legacy

    env = legacy_flow
    install_diagnosis(monkeypatch)
    with project_scope(env["scope"]):
        workflow = env["create"]()
        original = deepcopy(workflow.plan)
        # The phase has accepted analysis but has not approved modifications.
        handoff_exception(workflow, ComputeError("生成处置清单时缺少category映射"))
        workflow.refresh_from_db()
        assert workflow.status == "waiting_approval"
        recovery = legacy.projected_state(workflow)["nodes"]["apply"]["contextRecovery"]
        assert recovery["resumeCheckpoint"]["phase"] == "review_modifications"
        workflow = runtime.decide_flow(
            env["user"],
            workflow,
            {
                "nodeId": "apply",
                "decision": "retry_context",
                "feedback": "已核对映射，请恢复原处置确认步骤。",
                "revision": state(workflow)["revision"],
                "idempotencyKey": uuid4().hex,
            },
        )
        workflow.refresh_from_db()
        assert workflow.plan["phase"] == original["phase"]
        assert workflow.plan["stages"] == original["stages"]
        assert workflow.current_step == "apply"
        assert not workflow.plan["stages"][0].get("modificationsApproval")
