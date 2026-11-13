from copy import deepcopy
import json

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.catalog.models import DataResource
from apps.ecology.models import RemoteSensingProduct
from apps.ecology.monitoring import (
    monitoring_snapshot,
    normalize_product,
    register_product,
)
from apps.projects.context import ProjectScope, project_scope
from apps.projects.features import set_feature
from apps.projects.models import Project, ProjectFeature, ProjectMembership


@pytest.fixture
def setup_monitor():
    users = get_user_model()
    admin = users.objects.create_superuser("monitor-admin")
    reader = users.objects.create_user("monitor-reader")
    reader.user_permissions.add(Permission.objects.get(codename="browse_data"))
    project = Project.objects.create(code="monitor-test", name="监测测试")
    other = Project.objects.create(code="monitor-other", name="隔离项目")
    ProjectMembership.objects.create(user=reader, project=project)
    feature, _ = ProjectFeature.objects.get_or_create(key="ecology_monitor")
    set_feature(
        admin,
        feature,
        project=project,
        enabled=True,
        config={
            "title": "遥感监测",
            "source": "remote_sensing_products",
            "scenes": ["spartina", "wildfire"],
            "initialView": {"center": [112, 32], "zoom": 2, "regionZoom": 5},
        },
    )
    resource = DataResource.objects.create(
        project_tag=project,
        code="extent",
        name="真实分布面",
        data_type="vector",
        coordinate_system="EPSG:4326",
        storage_path="monitor_extent",
        maintainer=admin,
    )
    source = DataResource.objects.create(
        project_tag=project,
        code="source",
        name="来源",
        data_type="raster",
        coordinate_system="EPSG:4326",
        storage_path="source.tif",
        maintainer=admin,
    )
    manifest = {
        "schemaVersion": 1,
        "code": "historical-spartina",
        "name": "历史分布（时间待核实）",
        "resourceId": resource.pk,
        "scene": "spartina",
        "kind": "historical",
        "quality": "unverified",
        "observedStart": None,
        "observedEnd": None,
        "sourceResourceIds": [source.pk],
        "sourceLabel": "用户提供的历史成果",
        "limitations": ["观测时间未核实，未评估精度"],
        "interpretation": "只显示已有分布，不声明变化",
        "statistics": {"area_ha": None, "patch_count": 12881},
        "statisticsMethod": "斑块数来自原始要素计数；未计算面积",
        "model": None,
        "threshold": None,
        "timing": {
            "inputThrough": None,
            "validStart": None,
            "validEnd": None,
            "evidence": "原成果没有观测日期字段",
        },
    }
    return admin, reader, project, other, feature, resource, source, manifest


def publish(setup_monitor, **changes):
    admin, _, project, _, _, _, _, manifest = setup_monitor
    with project_scope(ProjectScope((project.pk,), project.pk, admin.pk)):
        return register_product(admin, {**manifest, **changes})[0]


def read(client, setup_monitor, **query):
    return client.get(
        "/api/ecology/monitoring/",
        {"scene": "spartina", **query},
        HTTP_X_PROJECT_ID=str(setup_monitor[2].pk),
    )


def test_empty_scene_does_not_create_products_or_simulated_readings(
    client, setup_monitor
):
    client.force_login(setup_monitor[1])
    response = read(client, setup_monitor)
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["nextBeforeId"] is None
    assert RemoteSensingProduct.objects.count() == 0
    assert read(client, setup_monitor, scene="wildfire").json()["items"] == []


def test_historical_product_keeps_unknown_time_missing_area_and_zero(
    client, setup_monitor
):
    publish(setup_monitor)
    client.force_login(setup_monitor[1])
    item = read(client, setup_monitor).json()["items"][0]
    assert item["observedStart"] is None
    assert item["timing"]["validStart"] is None
    assert item["metrics"][0]["value"] is None
    assert item["metrics"][1]["value"] == 12881
    row = publish(setup_monitor, code="true-zero", statistics={"patch_count": 0})
    assert row.metadata["monitoring"]["statistics"]["patch_count"] == 0


def test_register_is_idempotent_but_changed_published_content_is_rejected(
    setup_monitor,
):
    row = publish(setup_monitor)
    assert publish(setup_monitor).pk == row.pk
    with pytest.raises(ValidationError, match="新编码"):
        publish(setup_monitor, interpretation="不同的结论")
    assert RemoteSensingProduct.objects.count() == 1


def test_resource_and_all_provenance_permissions_are_rechecked(client, setup_monitor):
    _, reader, _, _, _, resource, source, _ = setup_monitor
    publish(setup_monitor)
    client.force_login(reader)
    assert len(read(client, setup_monitor).json()["items"]) == 1
    source.owner_only = True
    source.save()
    assert read(client, setup_monitor).json()["items"] == []
    source.owner_only = False
    source.save()
    resource.status = "inactive"
    resource.save()
    assert read(client, setup_monitor).json()["items"] == []


def test_cross_project_and_internal_sources_cannot_be_registered(setup_monitor):
    source = setup_monitor[6]
    external = DataResource.objects.create(
        project_tag=setup_monitor[3],
        code="external-source",
        name="外项目来源",
        data_type="raster",
        storage_path="external.tif",
    )
    with pytest.raises(PermissionDenied):
        publish(setup_monitor, sourceResourceIds=[external.pk])
    source.source = "workflow-upload:private-task"
    source.save()
    with pytest.raises(PermissionDenied):
        publish(setup_monitor)


def test_scene_feature_membership_and_authentication_gates(client, setup_monitor):
    admin, reader, project, _, feature, _, _, _ = setup_monitor
    assert (
        client.get(
            "/api/ecology/monitoring/", {"scene": "spartina"}, HTTP_X_PROJECT_ID="1"
        ).status_code
        == 401
    )
    assert read(client, setup_monitor).status_code == 404
    client.force_login(reader)
    assert (
        client.get("/api/ecology/monitoring/", {"scene": "spartina"}).status_code == 400
    )
    assert read(client, setup_monitor, scene="unknown").status_code == 400
    assert read(client, setup_monitor, limit=61).status_code == 400
    assert read(client, setup_monitor, beforeId=-1).status_code == 400
    set_feature(admin, feature, project=project, enabled=False)
    assert read(client, setup_monitor).status_code == 403
    set_feature(admin, feature, project=project, enabled=True)
    ProjectMembership.objects.filter(user=reader, project=project).delete()
    assert read(client, setup_monitor).status_code == 404


def test_model_output_and_forecast_cannot_be_invented_from_weight_name(setup_monitor):
    manifest = deepcopy(setup_monitor[-1])
    manifest.update(scene="wildfire", kind="model", statistics={})
    with pytest.raises(ValidationError, match="模型结果"):
        normalize_product(manifest)
    manifest["model"] = {
        "name": "UNet++",
        "version": "v1",
        "checkpointSha256": "a" * 64,
        "variant": "w8",
        "forecastLeadDays": None,
    }
    assert normalize_product(manifest)["timing"]["validStart"] is None
    manifest["timing"].update(
        inputThrough="2021-01-01", validStart="2021-01-09", validEnd="2021-01-16"
    )
    with pytest.raises(ValidationError, match="时效"):
        normalize_product(manifest)
    manifest["model"]["forecastLeadDays"] = 64
    with pytest.raises(ValidationError, match="一致"):
        normalize_product(manifest)
    manifest["model"]["forecastLeadDays"] = 8
    assert normalize_product(manifest)["timing"]["validStart"] == "2021-01-09"


def test_model_products_require_successful_import_and_all_task_sources(setup_monitor):
    from apps.compute.models import (
        AlgorithmResource,
        AlgorithmVersion,
        ComputeImport,
        ComputeInput,
        ComputeOutput,
        ComputeTask,
    )

    admin, _, project, _, _, resource, source, _ = setup_monitor
    model = {
        "name": "UNet",
        "version": "1",
        "checkpointSha256": "a" * 64,
        "variant": "single-channel",
        "forecastLeadDays": None,
    }
    with pytest.raises(ValidationError, match="计算中心"):
        publish(setup_monitor, kind="model", model=model)
    algorithm = AlgorithmResource.objects.create(
        project_tag=project,
        identifier="monitor-model",
        name="模型测试",
        created_by=admin,
    )
    version = AlgorithmVersion.objects.create(
        algorithm=algorithm,
        version="1",
        checksum="b" * 64,
        package_path="test-only",
        manifest={"qualityReport": {"file": "quality.json"}},
    )
    task = ComputeTask.objects.create(
        project_tag=project,
        owner=admin,
        version=version,
        name="隔离测试任务",
        status="succeeded",
        idempotency_key="monitor-test",
        request_hash="c" * 64,
    )
    ComputeInput.objects.create(task=task, key="image", resource=source)
    output = ComputeOutput.objects.create(
        task=task,
        key="mask",
        label="分类",
        kind="raster",
        file_name="mask.tif",
        path="test-only",
        size_bytes=1,
        checksum="d" * 64,
        metadata={
            "qualityCheck": {
                "version": 1,
                "status": "needs_review",
                "summary": "待复核",
                "metrics": {},
            },
            "knowledgeFacts": {},
        },
    )
    ComputeImport.objects.create(
        output=output,
        resource=resource,
        name=resource.name,
        requested_by=admin,
        status="ready",
    )
    resource.is_compute_result = True
    resource.save()
    with pytest.raises(ValidationError, match="审核"):
        publish(setup_monitor, kind="model", model=model)
    output.metadata["qualityCheck"]["status"] = "passed"
    output.save()
    with pytest.raises(ValidationError, match="全部来源"):
        publish(
            setup_monitor, kind="model", model=model, sourceResourceIds=[resource.pk]
        )
    assert (
        publish(setup_monitor, kind="model", model=model, quality="passed").metadata[
            "monitoring"
        ]["quality"]
        == "passed"
    )


@pytest.mark.parametrize(
    "statistics",
    [
        {"area_ha": float("nan")},
        {"area_ha": float("inf")},
        {"patch_count": 1.5},
        {"coverage_percent": 101},
        {"area_ha": -1},
        {"area_ha": True},
        {"mean_probability": 0.5},
    ],
)
def test_nonfinite_wrong_unit_and_invalid_statistics_rejected(
    setup_monitor, statistics
):
    with pytest.raises(ValidationError):
        normalize_product({**setup_monitor[-1], "statistics": statistics})


def test_cursor_pages_are_bounded_without_duplicate_products(client, setup_monitor):
    for index in range(4):
        publish(setup_monitor, code=f"historical-{index}")
    client.force_login(setup_monitor[1])
    first = read(client, setup_monitor, limit=2).json()
    second = read(client, setup_monitor, limit=2, beforeId=first["nextBeforeId"]).json()
    assert len(first["items"]) == len(second["items"]) == 2
    assert second["nextBeforeId"] is None
    assert not {item["id"] for item in first["items"]} & {
        item["id"] for item in second["items"]
    }


@pytest.mark.efficiency
def test_snapshot_reads_only_metadata_and_batches_dependency_access(
    setup_monitor, monkeypatch
):
    from apps.catalog import data_query

    monkeypatch.setattr(
        data_query,
        "get_resource_profile",
        lambda *args: pytest.fail("大屏目录不应读取科学文件"),
    )
    publish(setup_monitor)
    user, project = setup_monitor[1], setup_monitor[2]
    with project_scope(ProjectScope((project.pk,), project.pk, user.pk)):
        with CaptureQueriesContext(connection) as small:
            assert len(monitoring_snapshot(user, "spartina")["items"]) == 1
    for index in range(8):
        publish(setup_monitor, code=f"batched-{index}")
    with project_scope(ProjectScope((project.pk,), project.pk, user.pk)):
        with CaptureQueriesContext(connection) as large:
            assert len(monitoring_snapshot(user, "spartina")["items"]) == 9
    assert len(large) <= len(small)
    assert len(large) <= 7


def test_command_uses_existing_project_actor_and_catalog_ids(setup_monitor, tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(setup_monitor[-1]))
    call_command(
        "register_monitor_product",
        manifest=manifest,
        project=setup_monitor[2].code,
        actor=setup_monitor[0].username,
    )
    assert RemoteSensingProduct.objects.count() == 1
