from copy import deepcopy
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError

from apps.business_flows import execution_session, input_policy, main_loop, reports
from apps.business_flows.definitions import normalize_definition
from apps.business_flows.state import state

# Configuration: the smallest useful authored fixed-operator recipe.
SPEC = {
    "schemaVersion": 2,
    "adapter": "research_flow",
    "nodes": [
        {
            "id": "extract",
            "title": "提取冰川",
            "kind": "operator",
            "algorithmVersionId": 21,
            "contract": {
                "requiredOutputs": [{"name": "ice", "semanticType": "raster"}]
            },
        }
    ],
}


def task(spec):
    return SimpleNamespace(
        workflow_type="business_flow",
        detail="完成",
        plan={},
        parameters={
            "_businessFlow": {
                "versionId": 4,
                "name": "冰川解译",
                "definitionSnapshot": spec,
            }
        },
    )


def test_v2_uses_task_session_without_repeated_author_fields():
    definition = normalize_definition(SPEC, authored=True)
    assert definition == normalize_definition(definition)
    assert "executionMode" not in definition
    assert not input_policy.for_definition(definition)["allowScripts"]
    contract = definition["nodes"][0]["contract"]
    assert contract["goal"] == "提取冰川"
    assert contract["acceptance"] == []
    assert {"preflight_operator", "run_operator", "finish_node"} <= set(
        contract["tools"]
    )
    workflow = task(definition)
    execution_session.initialize(workflow)
    assert execution_session.session(workflow)["mode"] == "main_agent_v1"
    assert "主执行" not in execution_session.guidance(workflow, "extract")


def test_existing_definition_and_guards_are_not_rewritten():
    old = {
        **SPEC,
        "schemaVersion": 1,
        "nodes": [{"id": "extract", "title": "研究", "kind": "agent"}],
    }
    workflow = task(normalize_definition(old))
    execution_session.initialize(workflow)
    assert not execution_session.session(workflow)
    with pytest.raises(ValidationError, match="请省略executionMode"):
        normalize_definition({**SPEC, "executionMode": "nodes"}, authored=True)
    proposal = deepcopy(SPEC)
    proposal["nodes"][0]["contract"]["tools"] = ["finish_node"]
    with pytest.raises(ValidationError, match="真实算子"):
        normalize_definition(proposal, authored=True)


def test_unique_ready_node_and_terminal_progress_do_not_ask_model(monkeypatch):
    workflow = task(normalize_definition(SPEC, authored=True))
    execution_session.initialize(workflow)
    node = {"id": "extract"}
    calls = []
    monkeypatch.setattr(
        main_loop, "_control", lambda *args, **kwargs: calls.append(args)
    )
    assert main_loop.select_node(workflow, None, {}, [node]) is node
    assert not calls
    assert execution_session.session(workflow)["loop"]["activeNodeId"] == "extract"
    assert main_loop.finish_workflow(workflow, None, {})
    assert not calls
    assert execution_session.session(workflow)["loop"]["completed"]
    assert main_loop.select_node(workflow, None, {}, [node, {"id": "inspect"}]) is None
    assert len(calls) == 1


def test_report_prints_answer_once_without_audit_transcript():
    workflow = task(normalize_definition(SPEC, authored=True))
    snapshot = workflow.parameters["_businessFlow"]
    snapshot["inputVersions"] = {"image": {"name": "T43-10"}}
    value = state(workflow)
    value["answer"] = "本期提取冰川。没有可比前期。"
    value["events"] = [{"message": "重试日志"}]
    value["nodes"]["extract"].update(
        executor={"summary": value["answer"]},
        outputs={"evidence": [{"id": "output-11", "title": "冰川分类图"}]},
    )
    report = reports.render_report(workflow).decode()
    assert report.count(value["answer"]) == 1
    assert "冰川分类图（output-11）" in report and "T43-10" in report
    assert "重试日志" not in report
