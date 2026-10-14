"""Scenario orchestration with real database tasks and explicitly simulated execution."""

import json
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied

from apps.agent.demo_decisions import decide, validate_decision
from apps.agent.demo_results import read_output, validate_edits
from apps.agent.demo_workflow import (
    advance_demo,
    prepare_demo,
    confirm_demo,
    GRAPHS,
)
from apps.agent.models import AgentPolicy, AgentWorkflow
from apps.agent.policy import default_policy, validate_policy
from apps.agent.workflow import resume_waiting, run_workflow
from apps.catalog.models import DataResource
from apps.compute.models import (
    AlgorithmResource,
    AlgorithmVersion,
    ComputeTask,
    ComputeOutput,
    ComputeImport,
)
from apps.compute.packages import checksum, ComputeError
from apps.core.storage import app_path
from apps.projects.context import project_scope, ProjectScope
from apps.projects.models import ProjectMembership
from tests.integration.test_compute import setup_compute  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def demo(setup_compute, settings, monkeypatch):  # noqa: F811
    env = setup_compute
    settings.AGENT_MODELS = [
        {
            "alias": "mock",
            "name": "模拟测试模型",
            "model_id": "mock-demo",
            "base_url": "http://127.0.0.1:19100/v1",
            "agent": True,
        }
    ]
    env["owner"].user_permissions.add(
        *Permission.objects.filter(
            codename__in=["use_local_model", "use_data_agent", "query_data"],
        )
    )
    p = default_policy()
    p.update(
        operatorEnabled=True, maxResources=12, maxIterations=12, maxOperatorSteps=16
    )
    AgentPolicy.objects.create(value=p)
    env["policy"] = p
    scope = ProjectScope((env["project"].id,), env["project"].id, env["owner"].id)
    with project_scope(scope):
        inputs = {}
        for role, kind in {
            "early_image": "raster",
            "late_image": "raster",
            "valid_mask": "raster",
            "zones": "vector",
            "context": "table",
            "initial_map": "vector",
            "surveys": "table",
            "rules": "table",
        }.items():
            if kind == "table":
                inputs[role] = env["resource"].id
            else:
                inputs[role] = DataResource.objects.create(
                    name=role,
                    code=role,
                    data_type=kind,
                    maintainer=env["owner"],
                ).id
        env["inputs"] = inputs
        versions = {}
        kinds = {
            "image": "raster",
            "early_ndvi": "raster",
            "late_ndvi": "raster",
            "valid_mask": "raster",
            "change": "raster",
            "zones": "vector",
            "context": "table",
            "features": "vector",
            "surveys": "table",
            "rules": "table",
            "changes": "table",
        }
        for _, identifier, bindings in [
            *GRAPHS["ecology_investigation"],
            *GRAPHS["geology_correction"],
        ]:
            if identifier in versions:
                continue
            algorithm = AlgorithmResource.objects.create(
                identifier=identifier, name=identifier, created_by=env["owner"]
            )
            parameters = (
                [
                    {
                        "key": key,
                        "label": key,
                        "type": "band",
                        "input": "image",
                        "required": True,
                    }
                    for key in ("red", "nir")
                ]
                if identifier == "raster-ndvi"
                else []
            )
            version = AlgorithmVersion.objects.create(
                algorithm=algorithm,
                version="1.0.0",
                status="published",
                checksum="b" * 64,
                runtime_digest="sha256:" + "a" * 64,
                manifest={
                    "inputs": [
                        {"key": key, "label": key, "kind": kinds[key], "required": True}
                        for key in bindings
                    ],
                    "parameters": parameters,
                    "outputs": [],
                },
            )
            versions[identifier] = version
        env["versions"] = versions
        monkeypatch.setattr(
            "apps.compute.services.candidate",
            lambda r: {
                "id": r.id,
                "name": r.name,
                "kind": r.data_type,
                "bands": 2,
                "fields": ["region", "value"],
                "sizeBytes": 0,
                "geometryTypes": [],
            },
        )
        yield env


def scenario(env, kind="ecology_investigation"):
    roles = (
        ("early_image", "late_image", "valid_mask", "zones", "context")
        if kind == "ecology_investigation"
        else ("initial_map", "surveys", "rules")
    )
    inputs = {role: env["inputs"][role] for role in roles}
    return AgentWorkflow.objects.create(
        owner=env["owner"],
        model="mock",
        workflow_type=kind,
        goal="模拟资料的实际结果联动演示",
        resource_ids=list(set(inputs.values())),
        idempotency_key="scenario-" + kind,
        max_iterations=12,
        max_operator_steps=16,
        import_results=True,
        parameters={
            "early_date": "2024-06-01",
            "late_date": "2025-06-01",
            "red": 1,
            "nir": 2,
        },
        plan={"inputs": inputs, "knowledgeSelection": {"mode": "none", "domains": []}},
    )


def finish_task(workflow, *, review=False):
    workflow.refresh_from_db()
    stage = workflow.plan["stages"][workflow.plan["stageIndex"]]
    task = ComputeTask.objects.get(pk=stage["taskId"])
    task.status, task.stage, task.progress = "succeeded", "完成", 100
    task.save()
    key, kind = {
        "early_ndvi": ("ndvi", "raster"),
        "late_ndvi": ("ndvi", "raster"),
        "change": ("change", "raster"),
        "priority": ("priority", "vector"),
        "initial_check": ("issues", "table"),
        "geometry": ("repaired", "vector"),
        "check": ("issues", "table"),
        "edit": ("corrected", "vector"),
        "recheck": ("issues", "table"),
    }[stage["name"]]
    path = app_path("outputs", str(task.id), key + ".csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "zone_id,decline_fraction\nA,0.75\nB,0.2\n"
    if stage["name"] in {"initial_check", "check", "recheck"}:
        text = "feature_id,field,old_value,new_value,evidence_id,rule_id,status,reason,input_checksum\n"
        if stage["name"] in {"initial_check", "check"}:
            text += (
                "F2,contact_type,conformable,fault,E2,R2,repairable,调查资料确认断层接触,"
                + "c" * 64
                + "\n"
            )
    path.write_text(text, encoding="utf-8")
    metadata = {}
    if review:
        metadata = {
            "qualityCheck": {
                "version": 1,
                "status": "needs_review",
                "summary": "面积改变需人工核对",
                "metrics": {},
            },
            "knowledgeFacts": {},
        }
    return ComputeOutput.objects.create(
        task=task,
        key=key,
        label=key,
        kind=kind,
        file_name=path.name,
        path=path.relative_to(app_path()).as_posix(),
        size_bytes=path.stat().st_size,
        checksum=checksum(path),
        metadata=metadata,
    )


def mark_imports_ready(env):
    for record in ComputeImport.objects.filter(status="queued"):
        resource = DataResource.objects.create(
            name=record.name,
            code="result-" + str(record.output_id),
            data_type=record.output.kind,
            maintainer=env["owner"],
            source=f"compute-output:{record.storage_key}",
        )
        record.resource, record.status = resource, "ready"
        record.save()


def test_prepare_freezes_roles_and_rejects_stale_confirmation(demo):
    workflow = scenario(demo)
    run_workflow(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "waiting_approval"
    assert workflow.plan["stages"][0]["bindings"] == {"image": "early_image"}
    assert workflow.plan["stages"][1]["bindings"] == {"image": "late_image"}
    assert not ComputeTask.objects.exists()
    with pytest.raises(ComputeError, match="计划已变化"):
        confirm_demo(workflow, demo["owner"], demo["policy"], "old")
    DataResource.objects.filter(pk=demo["inputs"]["early_image"]).update(
        name="变化", updated_at="2026-01-01T00:00:00Z"
    )
    with pytest.raises(PermissionDenied, match="原始输入已变化"):
        confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)


@pytest.mark.parametrize("kind", ["ecology_investigation", "geology_correction"])
def test_real_task_import_chain_and_repeated_ticks_are_idempotent(demo, kind):
    workflow = scenario(demo, kind)
    run_workflow(workflow.id)
    workflow.refresh_from_db()
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    count = len(GRAPHS[kind])
    for index in range(count):
        run_workflow(workflow.id)
        workflow.refresh_from_db()
        assert workflow.status == "waiting_compute", workflow.detail
        task_id = workflow.plan["stages"][index]["taskId"]
        run_workflow(workflow.id)
        assert ComputeTask.objects.count() == index + 1
        output = finish_task(workflow)
        resume_waiting()
        resume_waiting()
        assert ComputeImport.objects.filter(output=output).count() == 1
        mark_imports_ready(demo)
        resume_waiting()
        workflow.refresh_from_db()
        assert workflow.plan["stageIndex"] == index + 1
        if index:
            assert any(
                r["kind"] == "output"
                for r in workflow.plan["stages"][index]["decision"]["evidenceRefs"]
            )
        assert (
            workflow.steps.filter(
                kind="submit_operator", compute_task_id=task_id
            ).count()
            == 1
        )
    run_workflow(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "succeeded", workflow.detail
    assert workflow.plan["finalDecision"]["modelMode"] == "mock"
    assert workflow.operator_steps == count
    assert len(workflow.result_resource_ids) == count
    if kind == "ecology_investigation":
        change = ComputeTask.objects.get(pk=workflow.plan["stages"][2]["taskId"])
        assert (
            change.input_records.get(key="early_ndvi").resource_id
            == workflow.plan["stages"][0]["outputs"][0]["resourceId"]
        )
        assert (
            change.input_records.get(key="late_ndvi").resource_id
            != change.input_records.get(key="early_ndvi").resource_id
        )
    else:
        edit = ComputeTask.objects.get(pk=workflow.plan["stages"][3]["taskId"])
        assert edit.input_records.count() == 4
        assert (
            edit.input_records.get(key="features").resource_id
            == workflow.plan["stages"][1]["outputs"][0]["resourceId"]
        )
        assert (
            DataResource.objects.filter(source=f"demo-changes:{workflow.id}").count()
            == 1
        )


def test_quality_review_preserves_check_and_resumes_manual_import(demo):
    workflow = scenario(demo, "geology_correction")
    prepare_demo(workflow, demo["owner"], demo["policy"])
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    advance_demo(workflow.id)
    output = finish_task(workflow, review=True)
    resume_waiting()
    workflow.refresh_from_db()
    assert workflow.status == "waiting_approval"
    assert workflow.plan["reviewOutputs"][0]["outputId"] == output.id
    assert not ComputeImport.objects.exists()
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    resume_waiting()
    record = ComputeImport.objects.get(output=output)
    assert record.request_source == ""
    assert output.metadata["qualityCheck"]["status"] == "needs_review"
    mark_imports_ready(demo)
    resume_waiting()
    workflow.refresh_from_db()
    assert workflow.plan["stageIndex"] == 1


def test_membership_revocation_stops_followup(demo):
    workflow = scenario(demo)
    prepare_demo(workflow, demo["owner"], demo["policy"])
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    advance_demo(workflow.id)
    finish_task(workflow)
    ProjectMembership.objects.filter(
        user=demo["owner"], project=demo["project"]
    ).delete()
    resume_waiting()
    workflow.refresh_from_db()
    assert workflow.status == "interrupted"
    assert not ComputeImport.objects.exists()


def test_output_reader_rechecks_checksum_and_workflow_identity(demo):
    workflow = scenario(demo)
    prepare_demo(workflow, demo["owner"], demo["policy"])
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    advance_demo(workflow.id)
    output = finish_task(workflow)
    assert (
        read_output(workflow, demo["owner"], demo["policy"], output)["checksum"]
        == output.checksum
    )
    app_path(output.path).write_text("changed", encoding="utf-8")
    with pytest.raises(ComputeError, match="文件内容已变化"):
        read_output(workflow, demo["owner"], demo["policy"], output)


def test_edits_require_exact_actual_issue_and_copy_stable_signature():
    row = {
        "feature_id": "F2",
        "field": "contact_type",
        "old_value": "conformable",
        "new_value": "fault",
        "evidence_id": "E2",
        "rule_id": "R2",
        "status": "repairable",
        "input_checksum": "a" * 64,
    }
    edit = {
        key: row[key]
        for key in (
            "feature_id",
            "field",
            "old_value",
            "new_value",
            "evidence_id",
            "rule_id",
        )
    }
    edit["reason"] = "实际调查支持"
    assert validate_edits([edit], [{"rows": [row]}])[0]["input_checksum"] == "a" * 64
    with pytest.raises(ComputeError, match="实际检查"):
        validate_edits([{**edit, "feature_id": "OTHER"}], [{"rows": [row]}])
    with pytest.raises(ComputeError, match="实际检查"):
        validate_edits([edit], [{"rows": [{**row, "status": "needs_review"}]}])
    assert (
        validate_edits(
            [{**edit, "old_value": ""}], [{"rows": [{**row, "old_value": ""}]}]
        )[0]["old_value"]
        == ""
    )
    assert validate_edits([], [{"rows": []}]) == []
    with pytest.raises(ComputeError, match="仍有可修复"):
        validate_edits([], [{"rows": [row]}])


def test_real_provider_receives_actual_table_and_rejects_fabricated_refs(
    demo, settings
):
    settings.AGENT_MODELS = [
        {
            "alias": "mock",
            "name": "实际provider测试",
            "model_id": "qwen-fixture",
            "base_url": "http://127.0.0.1:19100/v1",
            "agent": True,
        }
    ]
    workflow = scenario(demo)
    prepare_demo(workflow, demo["owner"], demo["policy"])
    refs = [{"kind": "output", "id": "31", "role": "statistics", "title": "statistics"}]
    decision = {
        "problem": "植被变化",
        "findings": ["A区下降比例0.75"],
        "judgement": "先查A",
        "uncertainties": ["原因待调查"],
        "nextAction": "ecology-priority",
        "algorithmReason": "依据变化统计",
        "evidenceRefs": refs,
        "resultSummary": "A区变化线索",
    }
    results = [
        {
            "outputId": 31,
            "checksum": "a" * 64,
            "key": "statistics",
            "rows": [{"zone_id": "A", "decline_fraction": "0.75"}],
        }
    ]
    with (
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=300),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            return_value=iter([json.dumps({"decision": decision, "edits": []})]),
        ) as stream,
    ):
        value, edits = decide(
            workflow,
            demo["owner"],
            demo["policy"],
            {"name": "priority", "identifier": "ecology-priority"},
            results,
            lambda: None,
        )
    assert value["modelMode"] == "real"
    assert not edits
    payload = json.loads(stream.call_args.args[1][-1]["content"])
    assert payload["actualResults"][0]["rows"][0]["decline_fraction"] == "0.75"
    assert {r["role"] for r in payload["inputRoles"]} == set(workflow.plan["inputs"])
    with pytest.raises(ComputeError, match="并非本次"):
        validate_decision(
            {**decision, "evidenceRefs": [{"kind": "output", "id": "999"}]},
            refs,
            "ecology-priority",
            require_output=True,
        )


def test_resource_policy_default_is_three_but_twelve_is_configurable(demo):
    assert default_policy()["maxResources"] == 3
    assert validate_policy({**demo["policy"], "maxResources": 12})["maxResources"] == 12


def test_scenario_budget_is_checked_before_confirming_plan(demo):
    workflow = scenario(demo, "geology_correction")
    workflow.max_iterations = 5
    with pytest.raises(ComputeError, match="至少设为6"):
        prepare_demo(workflow, demo["owner"], demo["policy"])
    assert not ComputeTask.objects.exists()


def test_cancel_stops_active_task_and_never_imports_it(demo):
    workflow = scenario(demo)
    prepare_demo(workflow, demo["owner"], demo["policy"])
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    advance_demo(workflow.id)
    AgentWorkflow.objects.filter(pk=workflow.id).update(cancel_requested=True)
    resume_waiting()
    workflow.refresh_from_db()
    assert workflow.status == "cancelled"
    assert workflow.cancel_requested
    assert ComputeTask.objects.get().status == "cancelled"
    assert not ComputeImport.objects.exists()
    advance_demo(workflow.id)
    assert ComputeTask.objects.count() == 1


def test_cancellation_during_model_analysis_is_preserved(demo):
    from apps.agent.demo_decisions import decide as actual_decide

    workflow = scenario(demo)
    prepare_demo(workflow, demo["owner"], demo["policy"])
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)

    def cancel_during_decision(*args, **kwargs):
        decision = actual_decide(*args, **kwargs)
        AgentWorkflow.objects.filter(pk=workflow.id).update(cancel_requested=True)
        return decision

    with patch("apps.agent.demo_workflow.decide", side_effect=cancel_during_decision):
        advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "cancelled"
    assert workflow.cancel_requested
    assert not ComputeTask.objects.exists()


def test_decision_approval_does_not_bypass_later_output_quality_review(demo):
    from apps.agent.demo_decisions import decide as actual_decide

    workflow = scenario(demo, "geology_correction")
    prepare_demo(workflow, demo["owner"], demo["policy"])
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)

    def ask_for_review(*args, **kwargs):
        decision, edits = actual_decide(*args, **kwargs)
        decision["nextAction"] = "request_review"
        return decision, edits

    with patch("apps.agent.demo_workflow.decide", side_effect=ask_for_review):
        advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "waiting_approval"
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    assert workflow.status == "queued"
    advance_demo(workflow.id)
    finish_task(workflow, review=True)
    resume_waiting()
    workflow.refresh_from_db()
    assert workflow.status == "waiting_approval"
    assert workflow.plan["stages"][0]["decisionApproved"]
    assert not workflow.plan["stages"][0].get("manualApproved")
    assert not ComputeImport.objects.exists()


def test_derived_resource_change_blocks_next_stage(demo):
    workflow = scenario(demo)
    prepare_demo(workflow, demo["owner"], demo["policy"])
    confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    advance_demo(workflow.id)
    finish_task(workflow)
    resume_waiting()
    mark_imports_ready(demo)
    resume_waiting()
    workflow.refresh_from_db()
    identity = workflow.result_resource_ids[0]
    DataResource.objects.filter(pk=identity).update(updated_at="2026-01-01T00:00:00Z")
    advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "interrupted"
    assert "下游输入" in workflow.detail
    assert ComputeTask.objects.count() == 1


def test_frozen_algorithm_change_blocks_confirmation(demo):
    workflow = scenario(demo)
    prepare_demo(workflow, demo["owner"], demo["policy"])
    demo["versions"]["raster-ndvi"].checksum = "d" * 64
    demo["versions"]["raster-ndvi"].save()
    with pytest.raises(PermissionDenied, match="算法版本已变化"):
        confirm_demo(workflow, demo["owner"], demo["policy"], workflow.plan_hash)
    assert not ComputeTask.objects.exists()
