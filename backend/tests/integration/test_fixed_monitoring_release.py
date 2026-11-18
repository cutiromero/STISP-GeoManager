"""Real queue lifecycle, explicit registration and previous-version protection."""

from uuid import UUID, uuid4

import pytest
from django.contrib.auth.models import Permission
from django.test import Client

from apps.agent.models import AgentPolicy, AgentWorkflowStep
from apps.agent.policy import default_policy
from apps.business_flows import catalog, engine
from apps.business_flows.fixed_monitoring import PRESETS, definition
from apps.business_flows.definitions import normalize_definition
from apps.catalog.models import DataResource
from apps.compute.models import ComputeImport, ComputeTask
from apps.compute.worker import run_task, process_import, task_scope
from apps.ecology.models import RemoteSensingProduct
from apps.projects.context import ProjectScope, project_scope
from apps.raster.models import RasterDataset
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_landcover_monitoring import imported  # noqa: F401

# ruff: noqa: F811

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("code", PRESETS)
def test_fixed_presets_use_frozen_inputs_and_outputs(code):
    spec = normalize_definition(definition(code, 1))
    assert spec["executionMode"] == "fixed"
    assert not spec["inputPreparation"]["allowScripts"]
    assert [node["kind"] for node in spec["nodes"]] == ["operator", "result"]
    op = spec["nodes"][0]
    assert op["inputBindings"].keys() == {
        row["key"] for row in spec["inputRequirements"]
    }
    assert {row["name"] for row in op["contract"]["requiredOutputs"]} == set(
        op["contract"]["importOutputs"]
    )


def test_fixed_flow_runs_real_queue_and_groups_task_without_model(
    setup_compute, monkeypatch
):  # noqa: F811
    env = setup_compute
    env["owner"].user_permissions.add(
        *Permission.objects.filter(
            codename__in=[
                "use_local_model",
                "use_data_agent",
                "query_data",
            ]
        )
    )
    AgentPolicy.objects.update_or_create(
        pk=1, defaults={"value": {**default_policy(), "operatorEnabled": True}}
    )
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
            env["admin"], {"code": "fixed-test", "name": "固定统计", "definition": spec}
        )
    headers = {"X-Project-Id": str(env["project"].pk)}
    payload = {
        "versionId": version.pk,
        "goal": "固定统计任务",
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

    monkeypatch.setattr("apps.compute.worker.execute", fake_container)
    engine.advance(workflow_id)
    task = ComputeTask._base_manager.get(owner=env["owner"])
    assert AgentWorkflowStep.objects.filter(
        workflow_id=workflow_id, compute_task_id=task.pk
    ).exists()
    with task_scope(task):
        run_task(task)
    engine.advance(workflow_id)
    record = ComputeImport.objects.get(output__task_id=task.pk)
    with task_scope(task):
        process_import(record)
    record.refresh_from_db()
    assert record.status == "ready", record.error
    for _ in range(3):
        engine.advance(workflow_id)
    detail = env["client"].get(
        f"/api/business-flows/runs/{workflow_id}/", headers=headers
    )
    assert detail.status_code == 200, detail.content
    assert detail.json()["status"] == "succeeded", detail.json()
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
