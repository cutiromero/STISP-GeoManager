"""A downstream operator consumes a real imported upstream CSV, never a fake ID."""

from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4

import pytest

from apps.agent.models import AgentWorkflowStep
from apps.business_flows import catalog, data_bindings, engine, runtime
from apps.business_flows.builtins import source_summary_definition
from apps.business_flows.state import state
from apps.compute.models import ComputeImport, ComputeInput, ComputeTask
from apps.compute.worker import process_import, task_scope
from apps.core.storage import app_path
from apps.projects.context import ProjectScope, project_scope
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_business_flow_operator_runtime import (  # noqa: F401
    operators,
    finish_task,
    advance,
)

# ruff: noqa: F811


@pytest.fixture
def chains(operators):
    env = operators

    def create():
        definition = source_summary_definition()
        output_key = next(
            row["key"]
            for row in env["version"].manifest["outputs"]
            if row["kind"] == "table"
        )
        node = {
            "id": "upstream",
            "title": "上游统计",
            "kind": "operator",
            "description": "先形成实际统计表",
            "instruction": "依据实际输入统计，不改原始资料。",
            "dependsOn": [],
            "dataRoles": ["source"],
            "algorithmVersionId": env["version"].pk,
            "parameters": deepcopy(env["body"]["parameters"]),
            "inputBindings": {"table": {"role": "source"}},
            "review": {"ai": False, "human": False, "maxRevisions": 0},
        }
        downstream = {
            **deepcopy(node),
            "id": "downstream",
            "title": "下游统计",
            "dependsOn": ["upstream"],
            "dataRoles": [],
            "inputBindings": {"table": {"nodeId": "upstream", "outputKey": output_key}},
            "parameters": {**env["body"]["parameters"], "method": "sum"},
        }
        finish = {**definition["nodes"][1], "dependsOn": ["downstream"]}
        definition["nodes"] = [node, downstream, finish]
        with project_scope(env["scope"]):
            _, version = catalog.register_flow(
                env["admin"],
                {
                    "code": "chain-" + uuid4().hex[:8],
                    "name": "上下游业务流",
                    "definition": definition,
                },
            )
            return runtime.start_flow(
                env["owner"],
                version,
                {
                    "model": "mock",
                    "goal": "按真实上游结果继续计算",
                    "inputs": {"source": env["resource"].pk},
                    "idempotencyKey": uuid4().hex,
                },
            )

    return {**env, "create_chain": create}


def upstream_ready(env):
    workflow = env["create_chain"]()
    advance(env, workflow)
    assert workflow.status == "waiting_compute", workflow.detail
    task_id = state(workflow)["nodes"]["upstream"]["computeTaskId"]
    output = finish_task(env, task_id, "UPSTREAM_ONLY")
    advance(env, workflow)
    assert state(workflow)["nodes"]["upstream"]["status"] == "succeeded", (
        workflow.detail
    )
    return workflow, output


def import_ready(env, output):
    with project_scope(env["scope"]):
        record = ComputeImport.objects.get(output=output)
        with task_scope(output.task):
            process_import(record)
        record.refresh_from_db()
        assert record.status == "ready", record.error
        return record


@pytest.mark.efficiency
def test_queued_import_requested_once_without_downstream_submission(chains):
    env = chains
    workflow, output = upstream_ready(env)
    real = data_bindings.request_output_import
    with patch(
        "apps.business_flows.data_bindings.request_output_import", wraps=real
    ) as requested:
        for _ in range(3):
            advance(env, workflow)
            assert workflow.status == "waiting_compute", workflow.detail
        assert requested.call_count == 1
    with project_scope(env["scope"]):
        record = ComputeImport.objects.get(output=output)
        assert (
            record.request_source == f"workflow:{workflow.pk}"
            and record.status == "queued"
        )
        assert ComputeTask.objects.count() == 1
        assert ComputeImport.objects.count() == 1
    assert not state(workflow)["nodes"]["downstream"].get("computeTaskId")


def test_upstream_csv_import_becomes_the_actual_downstream_compute_input(chains):
    env = chains
    workflow, output = upstream_ready(env)
    advance(env, workflow)
    imported = import_ready(env, output)
    assert imported.resource_id != env["resource"].pk
    assert imported.resource.project_tag_id == workflow.project_tag_id
    assert (
        imported.resource.data_type == "table" and imported.resource.is_compute_result
    )
    result = advance(env, workflow)
    assert workflow.status == "waiting_compute", workflow.detail
    downstream_id = state(workflow)["nodes"]["downstream"]["computeTaskId"]
    with project_scope(env["scope"]):
        bound = ComputeInput.objects.get(task_id=downstream_id, key="table")
        assert bound.resource_id == imported.resource_id
        assert bound.resource_id != env["resource"].pk
        assert output.pk in state(workflow)["consumedOutputs"]
    final = finish_task(env, downstream_id, "DOWNSTREAM_FINAL")
    advance(env, workflow)
    advance(env, workflow)
    result = advance(env, workflow)
    assert workflow.status == "succeeded", workflow.detail
    assert (
        result["resultOutputIds"] == [final.pk]
        and output.pk not in result["resultOutputIds"]
    )


@pytest.mark.parametrize("action", ["pause", "cancel"])
def test_controls_prevent_new_downstream_submission(chains, action):
    env = chains
    workflow, output = upstream_ready(env)
    advance(env, workflow)
    with project_scope(env["scope"]):
        runtime.control_flow(env["owner"], workflow, action)
    engine.advance(workflow.pk)
    workflow.refresh_from_db()
    with project_scope(env["scope"]):
        assert ComputeTask.objects.count() == 1
    assert workflow.status == ("paused" if action == "pause" else "cancelled")
    assert not state(workflow)["nodes"]["downstream"].get("computeTaskId")


def test_cancelled_flow_does_not_publish_a_queued_import(chains):
    env = chains
    workflow, output = upstream_ready(env)
    advance(env, workflow)
    with project_scope(env["scope"]):
        runtime.control_flow(env["owner"], workflow, "cancel")
    with project_scope(env["scope"]):
        record = ComputeImport.objects.get(output=output)
        with task_scope(output.task):
            process_import(record)
        record.refresh_from_db()
        assert record.status == "failed" and record.resource_id is None
        assert ComputeTask.objects.count() == 1


def test_pause_during_input_preparation_can_resume_the_chain(chains):
    env = chains
    workflow, output = upstream_ready(env)
    advance(env, workflow)
    with project_scope(env["scope"]):
        runtime.control_flow(env["owner"], workflow, "pause")
    with project_scope(env["scope"]):
        record = ComputeImport.objects.get(output=output)
        with task_scope(output.task):
            process_import(record)
        record.refresh_from_db()
        assert record.status in {"queued", "ready"}, record.error
        assert ComputeTask.objects.count() == 1
        runtime.control_flow(env["owner"], workflow, "resume")
    if record.status == "queued":
        import_ready(env, output)
    advance(env, workflow)
    assert workflow.status == "waiting_compute", workflow.detail
    with project_scope(env["scope"]):
        assert ComputeTask.objects.count() == 2


def test_quality_failure_cannot_be_overridden_by_a_flow_node_success(chains):
    env = chains
    workflow, output = upstream_ready(env)
    output.metadata = {
        **output.metadata,
        "qualityCheck": {
            "version": 1,
            "status": "needs_review",
            "summary": "统计需要核查",
            "metrics": {},
        },
        "knowledgeFacts": {},
    }
    output.save(update_fields=["metadata"])
    advance(env, workflow)
    assert workflow.status == "failed", workflow.detail
    with project_scope(env["scope"]):
        assert not ComputeImport.objects.exists() and ComputeTask.objects.count() == 1


def test_tampered_upstream_csv_cannot_be_imported(chains):
    env = chains
    workflow, output = upstream_ready(env)
    advance(env, workflow)
    path = app_path(output.path)
    path.write_text("region,value\nTAMPERED,999\n", encoding="utf-8")
    with project_scope(env["scope"]):
        record = ComputeImport.objects.get(output=output)
        with task_scope(output.task):
            process_import(record)
        record.refresh_from_db()
        assert record.status == "failed" and record.resource_id is None
        assert ComputeTask.objects.count() == 1


def test_live_derived_resource_acl_is_checked_before_downstream_submission(chains):
    from apps.catalog.models import DataResource

    env = chains
    workflow, output = upstream_ready(env)
    advance(env, workflow)
    imported = import_ready(env, output)
    with project_scope(env["scope"]):
        DataResource.objects.filter(pk=imported.resource_id).update(
            owner_only=True, maintainer=env["outsider"]
        )
    advance(env, workflow)
    assert workflow.status == "interrupted", workflow.detail
    with project_scope(env["scope"]):
        assert ComputeTask.objects.count() == 1


def test_a_same_owner_task_without_this_workflow_binding_is_not_an_input(chains):
    env = chains
    workflow, output = upstream_ready(env)
    with project_scope(env["scope"]):
        other = ComputeTask.objects.create(
            owner=env["owner"],
            version=env["version"],
            name="另一真实任务",
            status="succeeded",
            idempotency_key=uuid4().hex,
            request_hash=uuid4().hex,
        )
        state(workflow)["nodes"]["upstream"]["outputs"]["taskId"] = str(other.pk)
        workflow.save(update_fields=["plan"])
    advance(env, workflow)
    assert workflow.status == "interrupted", workflow.detail
    with project_scope(env["scope"]):
        assert not ComputeImport.objects.exists()


def test_upstream_node_must_be_fully_approved_not_only_computed(chains):
    from apps.compute.packages import ComputeError

    env = chains
    workflow, output = upstream_ready(env)
    state(workflow)["nodes"]["upstream"]["status"] = "waiting_human"
    node = workflow.parameters["_businessFlow"]["definitionSnapshot"]["nodes"][1]
    with project_scope(env["scope"]):
        policy = runtime.authorize(env["owner"], workflow)
        with pytest.raises(ComputeError, match="尚未通过全部审核"):
            data_bindings.prepare_inputs(
                workflow, env["owner"], policy, node, env["version"], {}
            )
        assert not ComputeImport.objects.exists()


def test_cross_project_upstream_task_is_never_consumed_even_with_forged_step(chains):
    env = chains
    workflow, output = upstream_ready(env)
    with project_scope(
        ProjectScope(
            (env["other_project"].pk,), env["other_project"].pk, env["admin"].pk, True
        )
    ):
        foreign = ComputeTask.objects.create(
            owner=env["owner"],
            project_tag_id=env["other_project"].pk,
            version=env["version"],
            name="另一项目任务",
            status="succeeded",
            idempotency_key=uuid4().hex,
            request_hash=uuid4().hex,
        )
    with project_scope(env["scope"]):
        AgentWorkflowStep.objects.create(
            workflow=workflow,
            sequence=workflow.steps.count() + 1,
            kind="submit_operator",
            compute_task_id=foreign.pk,
        )
        state(workflow)["nodes"]["upstream"]["outputs"]["taskId"] = str(foreign.pk)
        workflow.save(update_fields=["plan"])
    advance(env, workflow)
    assert workflow.status in {"interrupted", "failed"}
    with project_scope(env["scope"]):
        assert not ComputeImport.objects.exists()


def test_cancel_between_table_copy_and_publication_keeps_import_inactive(
    chains, monkeypatch
):
    from apps.catalog import importer

    env = chains
    workflow, output = upstream_ready(env)
    advance(env, workflow)
    original = importer.import_uploaded_table

    def cancel_after_copy(*args, **kwargs):
        result = original(*args, **kwargs)
        with project_scope(env["scope"]):
            runtime.control_flow(env["owner"], workflow, "cancel")
        return result

    monkeypatch.setattr(importer, "import_uploaded_table", cancel_after_copy)
    with project_scope(env["scope"]):
        record = ComputeImport.objects.get(output=output)
        with task_scope(output.task):
            process_import(record)
        record.refresh_from_db()
        assert record.status == "failed"
        assert record.resource_id and record.resource.status == "inactive"
        assert ComputeTask.objects.count() == 1
    workflow.refresh_from_db()
    assert workflow.status == "cancelled"


def test_role_binding_does_not_skip_its_declared_required_fields(chains):
    env = chains
    definition = source_summary_definition()
    definition["inputRequirements"].append(
        {
            **definition["inputRequirements"][0],
            "key": "context",
            "label": "背景资料",
            "requiredFields": ["missing_scientific_field"],
        }
    )
    definition["nodes"][0] = {
        "id": "calculate",
        "title": "统计",
        "description": "背景资料字段必须匹配",
        "instruction": "只读统计",
        "kind": "operator",
        "dependsOn": [],
        "dataRoles": ["source"],
        "algorithmVersionId": env["version"].pk,
        "parameters": env["body"]["parameters"],
        "inputBindings": {"table": {"role": "context"}},
        "review": {"ai": False, "human": False, "maxRevisions": 0},
    }
    definition["nodes"][1]["dependsOn"] = ["calculate"]
    with project_scope(env["scope"]):
        _, version = catalog.register_flow(
            env["admin"],
            {
                "code": "fields-" + uuid4().hex[:8],
                "name": "输入字段规范",
                "definition": definition,
            },
        )
        body = {
            "model": "mock",
            "inputs": {"source": env["resource"].pk, "context": env["resource"].pk},
            "idempotencyKey": uuid4().hex,
        }
        from django.core.exceptions import ValidationError
        from apps.agent.models import AgentWorkflow

        before = AgentWorkflow.objects.count()
        with patch("apps.agent.business_flow_execution.execute_node") as model:
            from apps.agent.policy import require_access

            _, _, preview = runtime._inputs(
                env["owner"],
                version.definition,
                body,
                require_access(env["owner"], "agent"),
                preview=True,
            )
            assert {item["role"]: item["status"] for item in preview["items"]} == {
                "source": "direct",
                "context": "unavailable",
            }
            assert preview["ready"] is False
            with pytest.raises(ValidationError):
                runtime.start_flow(env["owner"], version, body)
            model.assert_not_called()
        assert AgentWorkflow.objects.count() == before
        assert not ComputeTask.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_import_worker_cannot_observe_queue_before_waiting_state_is_committed(
    chains, monkeypatch
):
    import threading
    import time
    from django.db import OperationalError, close_old_connections, connections
    from apps.agent.models import AgentWorkflow

    env = chains
    workflow, output = upstream_ready(env)
    seen = []
    errors = []
    threads = []
    original = data_bindings.request_output_import

    def observe(identity):
        close_old_connections()
        try:
            with project_scope(env["scope"]):
                deadline = time.monotonic() + 4
                record = None
                while record is None and time.monotonic() < deadline:
                    try:
                        record = ComputeImport.objects.filter(pk=identity).first()
                    except OperationalError:
                        pass
                    if record is None:
                        time.sleep(0.005)
                if record is None:
                    raise AssertionError("queue row was not published")
                seen.append(AgentWorkflow.objects.get(pk=workflow.pk).status)
                with task_scope(record.output.task):
                    process_import(record)
                record.refresh_from_db()
                seen.append(record.status)
        except Exception as error:
            errors.append(error)
        finally:
            connections.close_all()

    def queued(*args, **kwargs):
        record = original(*args, **kwargs)
        child = threading.Thread(target=observe, args=(record.pk,), daemon=True)
        threads.append(child)
        child.start()
        # Give a concurrent queue reader an opportunity before the caller returns.
        time.sleep(0.04)
        return record

    monkeypatch.setattr(data_bindings, "request_output_import", queued)
    advance(env, workflow)
    for child in threads:
        child.join(timeout=5)
    assert threads and all(not child.is_alive() for child in threads)
    assert not errors, errors
    assert seen == ["waiting_compute", "ready"]
    with project_scope(env["scope"]):
        assert ComputeTask.objects.count() == 1
