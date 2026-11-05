"""HTTP Demo contracts and verified ecology evidence updates (isolated DB)."""

# ruff: noqa: F811

import json
from unittest.mock import patch

import pytest

from apps.agent.demo_decisions import decide, validate_decision
from apps.agent.demo_workflow import advance_demo, confirm_demo, prepare_demo
from apps.agent.models import AgentWorkflow
from apps.agent.workflow import resume_waiting, run_workflow, step
from apps.catalog.models import DataResource
from apps.compute.models import ComputeImport, ComputeTask
from apps.compute.packages import ComputeError
from apps.core.storage import table_data_path
from apps.knowledge.models import KnowledgeEntry
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import (
    demo,  # noqa: F401
    finish_task,
    mark_imports_ready,
    scenario,
)  # noqa: F401

pytestmark = pytest.mark.django_db


def payload(env, selection=None, **overrides):
    inputs = {
        key: env["inputs"][key]
        for key in ("early_image", "late_image", "valid_mask", "zones", "context")
    }
    value = {
        "workflowType": "ecology_investigation",
        "model": "mock",
        "goal": "依据两期影像与观测安排调查",
        "idempotencyKey": "dual-http-test-01",
        "resourceIds": sorted(set(inputs.values())),
        "inputs": inputs,
        "parameters": {
            "early_date": "2024-06-01",
            "late_date": "2025-06-01",
            "red": 1,
            "nir": 2,
        },
        "knowledgeSelection": selection or {"mode": "none", "domains": []},
    }
    value.update(overrides)
    return value


def post(env, value, path="/api/agent/workflows/"):
    return env["client"].post(
        path,
        json.dumps(value),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )


@pytest.mark.parametrize(
    "selection",
    [
        {"mode": "manual", "domains": ["remote_sensing"]},
        {"mode": "none", "domains": []},
    ],
)
def test_http_knowledge_selection_is_saved_and_limits_search(demo, selection):
    KnowledgeEntry.objects.create(
        title="NDVI植被有效像元",
        domain="remote_sensing",
        status="published",
        statement="NDVI需核对共同有效像元",
    )
    response = post(demo, payload(demo, selection))
    assert response.status_code == 202, response.content
    workflow = AgentWorkflow.objects.get(pk=response.json()["id"])
    assert workflow.plan["knowledgeSelection"] == selection
    run_workflow(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "waiting_approval", workflow.detail
    assert bool(workflow.evidence) == (selection["mode"] == "manual")
    assert all(item["domain"] == "remote_sensing" for item in workflow.evidence)


@pytest.mark.parametrize(
    "selection",
    [
        {"mode": "manual", "domains": []},
        {"mode": "none", "domains": ["geology"]},
        {"mode": "manual", "domains": ["missing"]},
    ],
)
def test_http_rejects_inconsistent_knowledge_selection(demo, selection):
    response = post(demo, payload(demo, selection))
    assert response.status_code == 400
    assert not AgentWorkflow.objects.exists()


def test_http_resource_ceiling_is_configurable_without_changing_default(demo):
    resources = payload(demo)["resourceIds"]
    while len(resources) < 13:
        resources.append(
            DataResource.objects.create(
                name="资料" + str(len(resources)),
                code="http-" + str(len(resources)),
                data_type="table",
            ).id
        )
    assert post(demo, payload(demo, resourceIds=resources)).status_code == 400
    response = post(demo, payload(demo, resourceIds=resources[:12]))
    assert response.status_code == 202, response.content
    assert len(response.json()["resourceIds"]) == 12


def test_http_legacy_step_serializes_null_decision(demo):
    workflow = scenario(demo)
    step(workflow, "legacy_step", message="旧步骤")
    response = demo["client"].get(
        f"/api/agent/workflows/{workflow.id}/",
        HTTP_X_PROJECT_ID=str(demo["project"].id),
    )
    assert response.status_code == 200, response.content
    assert response.json()["steps"][0]["decision"] is None


def test_http_review_confirmation_resumes_instead_of_active_early_return(demo):
    workflow = scenario(demo, "geology_correction")
    prepare_demo(workflow, demo["owner"], demo["policy"])
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    advance_demo(workflow.id)
    output = finish_task(workflow, review=True)
    resume_waiting()
    workflow.refresh_from_db()
    assert workflow.execute_operators and workflow.status == "waiting_approval"
    response = post(
        demo,
        {"planHash": workflow.plan_hash},
        f"/api/agent/workflows/{workflow.id}/confirm/",
    )
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "waiting_compute"
    resume_waiting()
    assert ComputeImport.objects.get(output=output).request_source == ""


def context_resource(name, extra=False):
    relative = "dual-test/" + name + ".csv"
    path = table_data_path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = "zone_id,date,event_type,land_use,evidence_id,source,confidence,value\nA,2025-03-01,drought,forest,E1,调查记录,0.9,1\n"
    if extra:
        raw += "B,2025-04-01,harvest,cropland,E2,新增调查,0.95,1\n"
    path.write_text(raw, encoding="utf-8")
    return DataResource.objects.create(
        name=name,
        code=name,
        data_type="table",
        file_format="CSV",
        storage_path="table/" + relative,
    )


@pytest.fixture
def completed_ecology(demo):
    demo["inputs"]["context"] = context_resource("old-observations").id
    workflow = scenario(demo)
    prepare_demo(workflow, demo["owner"], demo["policy"])
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    for _ in range(4):
        advance_demo(workflow.id)
        finish_task(workflow)
        resume_waiting()
        mark_imports_ready(demo)
        resume_waiting()
    advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "succeeded", workflow.detail
    demo["previous"] = workflow
    demo["inputs"]["context"] = context_resource("new-observations", extra=True).id
    return demo


def update_workflow(env, **overrides):
    value = payload(env, previousWorkflowId=str(env["previous"].id))
    value.update(overrides)
    response = post(env, value)
    assert response.status_code == 202, response.content
    return AgentWorkflow.objects.get(pk=response.json()["id"])


def test_update_runs_only_priority_with_verified_previous_change(completed_ecology):
    env = completed_ecology
    workflow = update_workflow(env)
    prepare_demo(workflow, env["owner"], env["policy"])
    assert [item["identifier"] for item in workflow.plan["stages"]] == [
        "ecology-priority"
    ]
    assert (
        workflow.plan["previousAnalysis"]["oldDecision"]
        == env["previous"].plan["finalDecision"]
    )
    assert workflow.plan["previousAnalysis"]["addedEvidence"][0]["evidence_id"] == "E2"
    confirm_demo(workflow, env["owner"], env["policy"], workflow.plan_hash)
    advance_demo(workflow.id)
    workflow.refresh_from_db()
    task = ComputeTask.objects.get(pk=workflow.plan["stages"][0]["taskId"])
    assert (
        task.input_records.get(key="change").resource_id
        == env["previous"].plan["stages"][2]["outputs"][0]["resourceId"]
    )
    finish_task(workflow)
    resume_waiting()
    mark_imports_ready(env)
    resume_waiting()
    advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "succeeded", workflow.detail
    assert workflow.iteration == 2 and workflow.operator_steps == 1
    assert ComputeTask.objects.count() == 5


def test_previous_analysis_pointer_cannot_grant_other_process_data(completed_ecology):
    from django.core.exceptions import PermissionDenied
    from apps.agent.workflow_resources import resolve_workflow_resource

    env = completed_ecology
    workflow = update_workflow(env)
    prepare_demo(workflow, env["owner"], env["policy"])
    unrelated = DataResource.objects.create(
        name="另一份过程材料",
        code="unrelated-process",
        data_type="table",
        source=f"workflow-working:{env['previous'].pk}:private",
        owner_only=True,
        maintainer=env["owner"],
    )
    workflow.plan["previous_change"] = unrelated.pk
    with pytest.raises(PermissionDenied):
        resolve_workflow_resource(env["owner"], env["policy"], unrelated.pk, workflow)


@pytest.mark.parametrize("changed", ["bands", "no_added", "same_context"])
def test_update_rejects_changed_semantics_or_no_new_evidence(
    completed_ecology, changed
):
    env = completed_ecology
    workflow = update_workflow(env)
    if changed == "bands":
        workflow.parameters["red"] = 2
    elif changed == "same_context":
        workflow.plan["inputs"]["context"] = env["previous"].plan["inputs"]["context"]
        workflow.resource_ids = list(workflow.plan["inputs"].values())
    else:
        path = table_data_path("dual-test/new-observations.csv")
        path.write_text(
            path.read_text(encoding="utf-8").split("B,2025")[0], encoding="utf-8"
        )
    with pytest.raises(ComputeError):
        prepare_demo(workflow, env["owner"], env["policy"])
    assert ComputeTask.objects.count() == 4


def test_update_rechecks_old_output_checksum_before_confirmation(completed_ecology):
    from apps.core.storage import app_path
    from apps.compute.models import ComputeOutput

    env = completed_ecology
    workflow = update_workflow(env)
    prepare_demo(workflow, env["owner"], env["policy"])
    output = ComputeOutput.objects.get(pk=workflow.plan["previousChange"]["outputId"])
    app_path(output.path).write_text("changed", encoding="utf-8")
    with pytest.raises(ComputeError, match="内容已变化"):
        confirm_demo(workflow, env["owner"], env["policy"], workflow.plan_hash)
    assert ComputeTask.objects.count() == 4


@pytest.mark.parametrize("restriction", ["owner", "project", "unfinished"])
def test_update_rejects_foreign_or_unfinished_previous_workflow(
    completed_ecology, restriction
):
    from django.core.exceptions import PermissionDenied

    env = completed_ecology
    workflow = update_workflow(env)
    previous = env["previous"]
    if restriction == "owner":
        AgentWorkflow.objects.filter(pk=previous.id).update(owner=env["outsider"])
    elif restriction == "project":
        from apps.projects.context import ProjectScope, project_scope

        pid = env["other_project"].id
        with project_scope(ProjectScope((pid,), pid, env["owner"].id)):
            foreign = AgentWorkflow.objects.create(
                owner=env["owner"],
                workflow_type="ecology_investigation",
                status="succeeded",
                idempotency_key="foreign-analysis-1",
            )
        workflow.plan["previousWorkflowId"] = str(foreign.id)
    else:
        AgentWorkflow.objects.filter(pk=previous.id).update(status="failed")
    with pytest.raises(PermissionDenied, match="当前用户与项目"):
        prepare_demo(workflow, env["owner"], env["policy"])
    assert ComputeTask.objects.count() == 4


def test_decision_requires_retrieved_knowledge_to_be_cited():
    value = {
        "problem": "问题",
        "findings": [],
        "judgement": "判断",
        "uncertainties": [],
        "nextAction": "finish",
        "algorithmReason": "原因",
        "evidenceRefs": [{"kind": "output", "id": "1"}],
    }
    refs = [
        {"kind": "output", "id": "1"},
        {"kind": "knowledge", "id": "2", "revision": 1},
    ]
    with pytest.raises(ComputeError, match="已检索知识"):
        validate_decision(value, refs, "finish", require_knowledge=True)


def test_real_provider_final_cannot_only_cite_old_statistics(demo, settings):
    settings.AGENT_MODELS = [
        {
            "alias": "mock",
            "name": "provider测试",
            "model_id": "qwen-fixture",
            "base_url": "http://127.0.0.1:19100/v1",
            "agent": True,
        }
    ]
    workflow = scenario(demo)
    prepare_demo(workflow, demo["owner"], demo["policy"])
    workflow.plan["stages"][-1]["taskId"] = "current-task"
    value = {
        "problem": "问题",
        "findings": [],
        "judgement": "判断",
        "uncertainties": [],
        "nextAction": "finish",
        "algorithmReason": "原因",
        "evidenceRefs": [{"kind": "output", "id": "1"}],
    }
    results = [
        {"outputId": 1, "taskId": "old-task", "key": "statistics", "rows": []},
        {"outputId": 2, "taskId": "current-task", "key": "statistics", "rows": []},
    ]
    with (
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=300),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            side_effect=[
                iter([json.dumps({"decision": value, "edits": []})]),
                iter([json.dumps({"decision": value, "edits": []})]),
            ],
        ),
    ):
        with pytest.raises(ComputeError, match="最近一次"):
            decide(
                workflow,
                demo["owner"],
                demo["policy"],
                {"name": "final_analysis", "identifier": "finish"},
                results,
                lambda: None,
            )


def test_changes_csv_is_readable_by_real_candidate_and_input_freeze(demo, tmp_path):
    import csv
    from apps.agent.demo_results import create_changes
    from apps.agent.tools import frame
    from apps.compute.data import candidate, freeze_input
    from apps.compute.models import ComputeInput

    workflow = scenario(demo, "geology_correction")
    issue = {
        "feature_id": "F2",
        "field": "contact_type",
        "old_value": "conformable",
        "new_value": "fault",
        "evidence_id": "E2",
        "rule_id": "R2",
        "status": "repairable",
        "input_checksum": "b" * 64,
    }
    edit = {
        key: value
        for key, value in issue.items()
        if key not in {"status", "input_checksum"}
    }
    edit["reason"] = "调查确认断层接触"
    resource = create_changes(
        workflow, demo["owner"], demo["policy"], [edit], [{"rows": [issue]}]
    )
    assert resource.storage_path.startswith("table/demo/workflows/")
    actual, _ = frame(resource)
    assert actual.iloc[0]["input_checksum"] == issue["input_checksum"]
    assert "feature_id" in candidate(resource)["fields"]
    task = ComputeTask.objects.create(
        owner=demo["owner"],
        version=demo["version"],
        name="修改输入验证",
        idempotency_key="changes-freeze-1",
        request_hash="a" * 64,
    )
    record = ComputeInput.objects.create(
        task=task,
        key="changes",
        resource=resource,
        snapshot={"updatedAt": resource.updated_at.isoformat()},
    )
    directory = tmp_path / "freeze"
    directory.mkdir()
    result = freeze_input(record, directory)
    assert result["sha256"]
    with (directory / "changes.csv").open(encoding="utf-8", newline="") as stream:
        frozen = list(csv.DictReader(stream))
    assert frozen[0]["input_checksum"] == issue["input_checksum"]
    assert frozen[0]["new_value"] == "fault"
    again = create_changes(
        workflow, demo["owner"], demo["policy"], [edit], [{"rows": [issue]}]
    )
    assert again.id == resource.id and again.updated_at == resource.updated_at


def test_missing_context_file_ends_workflow_with_visible_error(demo):
    resource = context_resource("missing-context")
    table_data_path("dual-test/missing-context.csv").unlink()
    demo["inputs"]["context"] = resource.id
    workflow = scenario(demo)
    prepare_demo(workflow, demo["owner"], demo["policy"])
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "failed"
    assert "文件不存在" in workflow.detail
    assert not ComputeTask.objects.exists()


def test_cancel_during_result_read_stops_import_and_closes_workflow(demo):
    from apps.agent.demo_results import read_results as actual_read

    workflow = scenario(demo)
    prepare_demo(workflow, demo["owner"], demo["policy"])
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    advance_demo(workflow.id)
    finish_task(workflow)

    def read_then_cancel(*args):
        result = actual_read(*args)
        AgentWorkflow.objects.filter(pk=workflow.id).update(cancel_requested=True)
        return result

    with patch("apps.agent.demo_workflow.read_results", side_effect=read_then_cancel):
        resume_waiting()
    workflow.refresh_from_db()
    assert workflow.status == "cancelled" and workflow.cancel_requested
    assert not ComputeImport.objects.exists()
    assert ComputeTask.objects.count() == 1


def test_cancel_when_import_becomes_ready_never_leaves_cancelled_queue(demo):
    from apps.agent.workflow_resources import (
        resolve_workflow_resource as actual_resolve,
    )

    workflow = scenario(demo)
    prepare_demo(workflow, demo["owner"], demo["policy"])
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    advance_demo(workflow.id)
    output = finish_task(workflow)
    resume_waiting()
    mark_imports_ready(demo)
    identity = ComputeImport.objects.get(output=output).resource_id

    def resolve_then_cancel(user, policy, resource_id, *args, **kwargs):
        result = actual_resolve(user, policy, resource_id, *args, **kwargs)
        if resource_id == identity:
            AgentWorkflow.objects.filter(pk=workflow.id).update(cancel_requested=True)
        return result

    with patch(
        "apps.agent.demo_workflow.resolve_workflow_resource",
        side_effect=resolve_then_cancel,
    ):
        resume_waiting()
    workflow.refresh_from_db()
    assert workflow.status == "cancelled" and workflow.cancel_requested
    assert workflow.plan["phase"] == "cancelled"
    assert ComputeTask.objects.count() == 1


@pytest.mark.parametrize("next_status", ["queued", "waiting_approval", "succeeded"])
def test_lifecycle_save_does_not_overwrite_new_cancellation(demo, next_status):
    from apps.agent.demo_workflow import _save

    workflow = scenario(demo)
    AgentWorkflow.objects.filter(pk=workflow.id).update(cancel_requested=True)
    workflow.status = next_status
    _save(workflow)
    workflow.refresh_from_db()
    assert workflow.status == "cancelled" and workflow.cancel_requested


def test_real_task_completion_updates_submit_timeline_status(demo):
    workflow = scenario(demo)
    prepare_demo(workflow, demo["owner"], demo["policy"])
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    advance_demo(workflow.id)
    assert workflow.steps.get(kind="submit_operator").status == "waiting"
    finish_task(workflow)
    resume_waiting()
    submitted = workflow.steps.get(kind="submit_operator")
    assert submitted.status == "succeeded"
    assert submitted.message == "计算已完成" and submitted.finished_at


def test_mock_final_summary_follows_actual_ranks_and_missing_coverage(demo):
    from apps.agent.demo_decisions import _final_mock_summary

    workflow = scenario(demo)
    prepare_demo(workflow, demo["owner"], demo["policy"])
    workflow.plan["stages"][-1]["taskId"] = "latest"
    rows = [
        {"zone_id": "stable", "zone_name": "甲区", "priority_rank": "3"},
        {"zone_id": "decline", "zone_name": "乙区", "priority_rank": "1"},
        {"zone_id": "cropland", "zone_name": "丙区", "priority_rank": "2"},
        {
            "zone_id": "missing",
            "zone_name": "丁区",
            "priority_rank": "",
            "priority_class": "优先补资料",
            "coverage": "0.2",
        },
    ]
    summary = _final_mock_summary(workflow, [{"taskId": "latest", "rows": rows}])
    assert "乙区 → 丙区 → 甲区" in summary
    assert "丁区覆盖20.0%" in summary and "模拟分析" in summary


def test_mock_geology_summary_uses_final_recheck_counts(demo):
    from apps.agent.demo_decisions import _final_mock_summary

    workflow = scenario(demo, "geology_correction")
    prepare_demo(workflow, demo["owner"], demo["policy"])
    workflow.plan["stages"][-1]["taskId"] = "latest"
    results = [
        {"taskId": "old", "rows": [{"issue_count": "9"}]},
        {
            "taskId": "latest",
            "rows": [{"issue_count": "1", "needs_review": "1", "repairable": "0"}],
        },
    ]
    summary = _final_mock_summary(workflow, results)
    assert "剩余1项问题" in summary and "待核实1项" in summary
