"""Real queue lifecycle, explicit registration and previous-version protection."""

from uuid import UUID, uuid4

import pytest
from django.contrib.auth.models import Permission
from django.test import Client

from apps.agent.models import AgentWorkflow, AgentWorkflowStep
from apps.business_flows import catalog, engine
from apps.business_flows.monitoring_presets import PRESETS, definition
from apps.business_flows.definitions import normalize_definition
from apps.business_flows.execution_session import session
from apps.catalog.models import DataResource
from apps.compute.models import ComputeImport, ComputeTask
from apps.compute.worker import run_task, process_import, task_scope
from apps.ecology.models import RemoteSensingProduct
from apps.projects.context import ProjectScope, project_scope
from apps.raster.models import RasterDataset
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_landcover_monitoring import imported  # noqa: F401
from tests.integration.test_business_flow_operator_runtime import operators  # noqa: F401
from tests.integration.test_business_flow_node_tools import action, install

# ruff: noqa: F811

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("code", PRESETS)
def test_presets_keep_main_agent_and_safe_adaptation(code):
    spec = normalize_definition(definition(code, 1))
    assert spec["executionMode"] == "main_agent"
    assert spec["inputPreparation"]["allowScripts"]
    assert spec["inputPreparation"]["reviewScripts"]
    assert "prepare_input" in spec["nodes"][0]["contract"]["tools"]
    assert [node["kind"] for node in spec["nodes"]] == ["operator", "result"]
    op = spec["nodes"][0]
    assert op["inputBindings"].keys() == {
        row["key"] for row in spec["inputRequirements"]
    }
    assert {row["name"] for row in op["contract"]["requiredOutputs"]} == set(
        op["contract"]["importOutputs"]
    )


def test_one_main_agent_runs_real_queue_and_groups_task(operators, monkeypatch):
    env = operators
    spec = definition("huanjiang-landcover", env["version"].pk)
    operator = spec["nodes"][0]
    operator.update(
        dataRoles=["table"],
        inputBindings={"table": {"role": "table"}},
        parameters=env["body"]["parameters"],
    )
    output_key = env["version"].manifest["outputs"][0]["key"]
    operator["contract"].update(
        requiredOutputs=[{"name": output_key, "semanticType": "table"}],
        importOutputs=[output_key],
    )
    spec["inputRequirements"][0].update(key="table", dataTypes=["table"])
    scope = ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    with project_scope(scope):
        flow, version = catalog.register_flow(
            env["admin"],
            {"code": "monitoring-agent-test", "name": "监测统计", "definition": spec},
        )
    headers = {"X-Project-Id": str(env["project"].pk)}
    payload = {
        "versionId": version.pk,
        "goal": "监测统计任务",
        "model": "mock",
        "inputs": env["body"]["inputs"],
        "parameters": {},
        "idempotencyKey": uuid4().hex,
    }
    url = f"/api/business-flows/{flow.pk}/start/"
    response = env["client"].post(
        url, payload, content_type="application/json", headers=headers
    )
    assert response.status_code == 202, response.content
    workflow_id = response.json()["id"]
    assert (
        env["client"]
        .post(url, payload, content_type="application/json", headers=headers)
        .json()["id"]
        == workflow_id
    )

    def fake_container(attempt, package, inputs, results, manifest, heartbeat):
        assert "hidden" not in (inputs / "table.csv").read_text()
        (results / "summary.csv").write_text(
            "region,value\nA,3\nB,8\n", encoding="utf-8"
        )
        heartbeat(True)

    def finish_interpret(packet):
        output = next(
            row["id"] for row in packet["evidence"] if row["id"].startswith("output-")
        )
        return action(
            "finish_node",
            summary="已核对实际统计",
            outputs=[
                {"name": output_key, "semanticType": "table", "evidenceId": output}
            ],
            evidenceIds=[output],
            limitations=[],
        )

    def finish_delivery(packet):
        evidence = packet["evidence"][0]["id"]
        return action(
            "finish_node",
            summary="已交付任务成果与统计",
            outputs=[
                {"name": "analysis", "semanticType": "analysis", "evidenceId": evidence}
            ],
            evidenceIds=[evidence],
            limitations=[],
        )

    calls = install(
        monkeypatch,
        [
            action("start_node", nodeId="interpret"),
            action("preflight_operator"),
            action("run_operator", usePreflight=True),
            finish_interpret,
            action("start_node", nodeId="finish"),
            finish_delivery,
            action("finish_workflow", summary="已核对和整理本次统计"),
        ],
    )
    monkeypatch.setattr("apps.compute.worker.execute", fake_container)
    workflow = AgentWorkflow._base_manager.get(pk=workflow_id)
    assert session(workflow).get("id") and workflow.model == "mock"
    for _ in range(4):
        engine.advance(workflow_id)
    task = ComputeTask._base_manager.get(owner=env["owner"])
    assert AgentWorkflowStep.objects.filter(
        workflow_id=workflow_id, compute_task_id=task.pk
    ).exists()
    with task_scope(task):
        run_task(task)
    for _ in range(8):
        if ComputeImport.objects.filter(output__task_id=task.pk).exists():
            break
        engine.advance(workflow_id)
    record = ComputeImport.objects.get(output__task_id=task.pk)
    with task_scope(task):
        process_import(record)
    record.refresh_from_db()
    assert record.status == "ready", record.error
    for _ in range(10):
        engine.advance(workflow_id)
        workflow.refresh_from_db()
        if workflow.status == "succeeded":
            break
    assert len(calls) == 7
    assert ComputeTask._base_manager.filter(owner=env["owner"]).count() == 1
    detail = env["client"].get(
        f"/api/business-flows/runs/{workflow_id}/", headers=headers
    )
    assert detail.status_code == 200, detail.content
    assert detail.json()["status"] == "succeeded", detail.json()
    assert detail.json()["mainAgent"]["id"] == session(workflow)["id"]
    assert detail.json()["resultResourceIds"] == [record.resource_id]
    assert not RemoteSensingProduct._base_manager.exists()
    catalogue = env["client"].get(
        f"/api/compute/result-groups/?groupId={workflow_id}", headers=headers
    )
    assert catalogue.status_code == 200, catalogue.content
    (group,) = catalogue.json()["items"]
    assert UUID(group["id"]) == UUID(workflow_id)
    assert group["items"][0]["resourceId"] == record.resource_id
    assert not group["items"][0]["registered"]
    raw = env["client"].get(
        "/api/catalog/resources/?excludeComputeResults=1", headers=headers
    )
    assert raw.status_code == 200, raw.content
    assert record.resource_id not in [row["id"] for row in raw.json()["items"]]


def test_formal_registration_requires_owner_and_uses_existing_registry(
    imported, monkeypatch
):  # noqa: F811
    env, task, source, record = imported
    env["owner"].user_permissions.add(
        *Permission.objects.filter(codename="load_raster_layer")
    )
    scope = env["scope"]
    http = {"X-Project-Id": str(scope.selected)}
    with project_scope(scope):
        dataset = RasterDataset.objects.create(
            name="范围",
            code="formal-boundary",
            data_resource=record.resource,
            status="ready",
            bounds_4326=[100, 30, 104, 34],
        )
    fake_style = {
        "datasetId": dataset.id,
        "styleHash": "123",
        "bounds4326": dataset.bounds_4326,
    }
    monkeypatch.setattr(
        "apps.ecology.official_monitoring.register_tile_style", lambda *args: fake_style
    )
    monkeypatch.setattr(
        "apps.ecology.official_monitoring.tile_style_is_ready", lambda *args: True
    )
    read_url = "/api/ecology/monitoring/official/?scene=landcover"
    publish_url = "/api/ecology/monitoring/registration/"
    assert env["client"].get(read_url, headers=http).json()["items"] == []
    admin = Client()
    admin.force_login(env["admin"])
    value = {"outputId": record.output_id}
    assert (
        admin.post(
            publish_url, value, headers=http, content_type="application/json"
        ).status_code
        == 404
    )
    result = env["client"].post(
        publish_url, value, headers=http, content_type="application/json"
    )
    assert result.status_code == 200, result.content
    assert (
        env["client"]
        .post(publish_url, value, headers=http, content_type="application/json")
        .json()
        == result.json()
    )
    with project_scope(scope):
        prior = RemoteSensingProduct.objects.get(pk=result.json()["id"])
        another = RemoteSensingProduct.objects.create(
            name="同一区域同一期新登记",
            product_code="different-registration",
            project_tag=prior.project_tag,
            product_type=prior.product_type,
            metadata=prior.metadata,
            data_resource=prior.data_resource,
        )
    items = env["client"].get(read_url, headers=http).json()["items"]
    assert [item["id"] for item in items] == [another.pk]
    with project_scope(scope):
        DataResource.objects.filter(pk=source.pk).update(
            owner_only=True, maintainer_id=env["outsider"].pk
        )
    assert env["client"].get(read_url, headers=http).json()["items"] == []


def test_publication_retains_actual_original_acl_after_agent_adaptation(imported):
    from django.core.exceptions import PermissionDenied
    from apps.compute.models import ComputeInput, ComputeOutput
    from apps.ecology.product_sources import source_resource_ids

    env, task, source, _ = imported
    with project_scope(env["scope"]):
        workflow = AgentWorkflow.objects.create(
            owner=env["owner"],
            workflow_type="business_flow",
            status="succeeded",
            goal="有安全适配的解译",
            model="mock",
            idempotency_key=uuid4().hex,
        )
        derived = DataResource.objects.create(
            name="本任务工作副本",
            code="adapted-qa",
            data_type="raster",
            storage_path="read-only-derived.tif",
            coordinate_system="EPSG:3857",
            maintainer=env["owner"],
            owner_only=True,
            source=f"workflow-working:{workflow.pk}:input-adapter:image",
        )
        adapter = ComputeTask.objects.create(
            owner=env["owner"],
            version=task.version,
            status="succeeded",
            idempotency_key=uuid4().hex,
            request_hash="a" * 64,
        )
        ComputeInput.objects.create(task=adapter, key="source", resource=source)
        output = ComputeOutput.objects.create(
            task=adapter,
            key="prepared",
            kind="raster",
            file_name="prepared.tif",
            path="prepared.tif",
            size_bytes=10,
            checksum="c" * 64,
        )
        ComputeImport.objects.create(
            output=output,
            resource=derived,
            status="ready",
            requested_by=env["owner"],
            request_source=f"workflow:{workflow.pk}",
        )
        ComputeInput.objects.filter(task=task).update(resource=derived)
        AgentWorkflowStep.objects.create(
            workflow=workflow,
            sequence=1,
            compute_task_id=task.pk,
            kind="submit_operator",
        )
        edge = AgentWorkflowStep.objects.create(
            workflow=workflow,
            sequence=2,
            compute_task_id=adapter.pk,
            kind="input_adapted",
            output_refs={"resourceIds": [derived.pk], "outputIds": [output.pk]},
        )
        assert source_resource_ids(task) == [source.pk]
        edge.output_refs = {"resourceIds": [derived.pk], "outputIds": [output.pk + 1]}
        edge.save(update_fields=["output_refs"])
        with pytest.raises(PermissionDenied, match="缺少可确认"):
            source_resource_ids(task)
