"""Generic geology workflow: task uploads, field confirmation and working copies."""

# ruff: noqa: F811
import json
import uuid

import geopandas as gpd
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from shapely.geometry import LineString, box

from apps.agent.demo_workflow import confirm_demo, prepare_demo
from apps.agent.generic_inputs import (
    coverage_copy,
    faults_copy,
    lithology_copy,
    units_override,
)
from apps.agent.geology_generic import heuristic_targets, utm_epsg, validate_mapping
from apps.agent.models import AgentWorkflow, WorkflowUpload
from apps.agent.workflow_creation import create_workflow
from apps.agent.workflow_uploads import store_upload
from apps.catalog.models import DataResource
from apps.compute.packages import ComputeError
from apps.projects.context import ProjectScope, project_scope
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo  # noqa: F401

pytestmark = pytest.mark.django_db

GEOLOGY = {
    "type": "FeatureCollection",
    "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
    "features": [
        {
            "type": "Feature",
            "properties": {"DCMC": name, "DH": code, "MJ": area},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [x, 35.6],
                        [x + 0.01, 35.6],
                        [x + 0.01, 35.61],
                        [x, 35.61],
                        [x, 35.6],
                    ]
                ],
            },
        }
        for x, name, code, area in [
            (97.00, "八宝山组二段", "T3b2", 1.2),
            (97.01, "闹仓坚沟组一段", "O1n1", 0.8),
            (97.02, "全新统冲积物", "Qh", 2.4),
            (97.03, "八宝山组二段", "T3b2", 0.5),
        ]
    ],
}


def geojson(name="八宝山幅地质图.geojson", value=GEOLOGY):
    return SimpleUploadedFile(
        name, json.dumps(value, ensure_ascii=False).encode(), "application/geo+json"
    )


@pytest.fixture
def generic(demo):
    scope = ProjectScope((demo["project"].id,), demo["project"].id, demo["owner"].id)
    with project_scope(scope):
        rules = DataResource.objects.create(
            name="综合推理试用规则",
            code="geology-multi-rules",
            data_type="table",
            maintainer=demo["owner"],
        )
        yield {**demo, "rules": rules, "batch": uuid.uuid4().hex}


def test_upload_is_profiled_owner_only_and_hidden_from_catalog(generic):
    response = generic["client"].post(
        "/api/agent/workflow-uploads/",
        {"batchId": generic["batch"], "file": geojson()},
        HTTP_X_PROJECT_ID=str(generic["project"].id),
    )
    assert response.status_code == 201, response.content
    value = response.json()
    assert value["roleHint"] == "lithology"
    assert value["profile"]["featureCount"] == 4
    fields = {field["name"]: field for field in value["profile"]["fields"]}
    assert fields["DCMC"]["distinctCount"] == 3
    assert "八宝山组二段" in fields["DCMC"]["samples"]
    resource = DataResource.objects.get(pk=value["resourceId"])
    assert resource.owner_only and resource.maintainer == generic["owner"]
    assert resource.source == "workflow-upload:" + generic["batch"]
    listing = generic["client"].get(
        "/api/catalog/resources/", HTTP_X_PROJECT_ID=str(generic["project"].id)
    )
    assert resource.id not in [item["id"] for item in listing.json()["items"]]
    admin = generic["client"].get(
        "/api/admin/data/resources/", HTTP_X_PROJECT_ID=str(generic["project"].id)
    )
    assert admin.status_code == 200, admin.content
    assert resource.id not in [item["id"] for item in admin.json()["items"]]
    batch = generic["client"].get(
        "/api/agent/workflow-uploads/",
        {"batchId": generic["batch"]},
        HTTP_X_PROJECT_ID=str(generic["project"].id),
    )
    assert [item["id"] for item in batch.json()["items"]] == [value["id"]]


def test_name_rules_pick_stratum_and_code_fields():
    profile = {
        "fields": [
            {"name": "MJ", "type": "number", "samples": ["1.2"], "distinctCount": 4},
            {
                "name": "DCMC",
                "type": "text",
                "samples": ["八宝山组二段"],
                "distinctCount": 3,
            },
            {"name": "DH", "type": "text", "samples": ["T3b2"], "distinctCount": 3},
        ]
    }
    targets = {
        item["key"]: item["field"] for item in heuristic_targets("lithology", profile)
    }
    assert targets == {"name": "DCMC", "geo_sym": "DH", "conf": None}


def _create(generic, inputs, key="generic-workflow-1"):
    return create_workflow(
        generic["owner"],
        generic["project"].id,
        {
            "workflowType": "geology_generic",
            "goal": "检查上传的地质图",
            "model": "mock",
            "idempotencyKey": key,
            "inputs": inputs,
            "uploadBatchId": generic["batch"],
        },
    )


def test_batch_binds_once_and_retry_returns_same_workflow(generic):
    upload = store_upload(
        generic["owner"], generic["project"].id, geojson(), generic["batch"]
    )
    workflow = _create(generic, {"lithology": upload.resource_id})
    assert workflow.plan["uploadInputs"] == {"lithology": upload.resource_id}
    assert workflow.plan["rulesResourceId"] == generic["rules"].id
    assert WorkflowUpload.objects.get(pk=upload.pk).workflow_id == workflow.id
    assert _create(generic, {"lithology": upload.resource_id}).id == workflow.id
    with pytest.raises(ComputeError, match="已用于"):
        _create(generic, {"lithology": upload.resource_id}, key="generic-workflow-2")
    with pytest.raises(ComputeError, match="已用于任务"):
        store_upload(
            generic["owner"], generic["project"].id, geojson(), generic["batch"]
        )


def test_roles_must_come_from_batch_and_match_geometry(generic):
    upload = store_upload(
        generic["owner"], generic["project"].id, geojson(), generic["batch"]
    )
    with pytest.raises(ComputeError, match="本次任务上传"):
        _create(generic, {"lithology": generic["rules"].id})
    polygon = store_upload(
        generic["owner"], generic["project"].id, geojson("面.geojson"), generic["batch"]
    )
    with pytest.raises(ComputeError, match="几何类型"):
        _create(
            generic, {"lithology": upload.resource_id, "faults": polygon.resource_id}
        )


def test_mapping_review_waits_then_accepts_only_real_fields(generic):
    upload = store_upload(
        generic["owner"], generic["project"].id, geojson(), generic["batch"]
    )
    workflow = _create(generic, {"lithology": upload.resource_id})
    prepare_demo(workflow, generic["owner"], generic["policy"])
    workflow.refresh_from_db()
    assert (workflow.status, workflow.plan["phase"]) == (
        "waiting_approval",
        "review_mapping",
    )
    review = workflow.plan["fieldMappingReview"]
    assert review["modelMode"] == "mock" and review["questions"] == []
    assert {t["key"]: t["field"] for t in review["roles"][0]["targets"]}[
        "name"
    ] == "DCMC"
    for mapping, message in [
        ({"lithology": {"name": "不存在"}}, "没有字段"),
        ({"lithology": {"geo_sym": "DH"}}, "请指定"),
        ({"lithology": {"name": "DCMC", "geo_sym": "DCMC"}}, "同一字段"),
    ]:
        with pytest.raises(ComputeError, match=message):
            validate_mapping(review, mapping)
    confirm_demo(
        workflow,
        generic["owner"],
        generic["policy"],
        workflow.plan_hash,
        field_mapping={"lithology": {"name": "DCMC", "geo_sym": "DH"}},
    )
    workflow = AgentWorkflow.objects.get(pk=workflow.pk)
    assert (workflow.status, workflow.plan["phase"]) == ("queued", "build_inputs")
    assert workflow.plan["confirmedMapping"]["lithology"]["geo_sym"] == "DH"
    assert workflow.plan["fieldMappingReview"]["confirmed"] is True


def test_working_copies_keep_canonical_fields_and_fill_absent_inputs():
    source = gpd.GeoDataFrame(
        {
            "DCMC": ["八宝山组二段", "", "冲积物"],
            "DH": ["T3b2", "O1n1", ""],
            "X": [1, 2, 3],
        },
        geometry=[box(0, 0, 10, 10), box(10, 0, 20, 10), box(20, 0, 30, 10)],
        crs=32646,
    )
    lithology = lithology_copy(source, {"name": "DCMC", "geo_sym": "DH"}, 32646)
    assert list(lithology.columns) == ["feature_id", "name", "geo_sym", "geometry"]
    assert list(lithology.feature_id) == ["F00001", "F00002", "F00003"]
    assert list(lithology.name) == ["八宝山组二段", "未命名单元", "冲积物"]
    assert list(lithology.geo_sym) == ["T3b2", "O1n1", "冲积物"]
    coverage = coverage_copy(None, {}, lithology)
    assert coverage.geometry.iloc[0].covers(lithology.union_all())
    faults = gpd.GeoDataFrame(
        {"BH": ["a", "b"]},
        geometry=[LineString([(5, 5), (50, 5)]), LineString([(100, 100), (120, 120)])],
        crs=32646,
    )
    clipped, dropped = faults_copy(faults, coverage)
    assert dropped == 1 and list(clipped.line_id) == ["S00001"]
    assert clipped.geometry.iloc[0].length < 32
    empty, _ = faults_copy(None, coverage)
    assert empty.empty and list(empty.columns) == ["line_id", "geometry"]


def test_unit_table_overrides_and_zone_projection():
    import pandas as pd

    frame = pd.DataFrame(
        {
            "DH": ["T3b2", "Qh"],
            "MC": ["八宝山组二段", "全新统"],
            "NL": ["212", "x"],
            "YL": ["是", "否"],
        }
    )
    value = units_override(
        frame, {"code": "DH", "name": "MC", "age_ma": "NL", "favorable": "YL"}
    )
    assert value["units"]["T3b2"] == {"age_ma": 212.0, "favorable": True}
    assert value["units"]["Qh"] == {"favorable": False}
    assert value["aliases"] == {"八宝山组二段": "T3b2", "全新统": "Qh"}
    assert utm_epsg([96.8, 35.6, 97.4, 35.9]) == 32647
    assert utm_epsg([-70.5, -33.6, -70.4, -33.4]) == 32719


def test_unbound_upload_can_be_deleted_but_bound_is_kept(generic):
    first = store_upload(
        generic["owner"], generic["project"].id, geojson(), generic["batch"]
    )
    second = store_upload(
        generic["owner"],
        generic["project"].id,
        geojson("副本.geojson"),
        generic["batch"],
    )
    path = f"/api/agent/workflow-uploads/{second.id}/"
    response = generic["client"].delete(
        path, HTTP_X_PROJECT_ID=str(generic["project"].id)
    )
    assert response.status_code == 204
    assert DataResource.objects.get(pk=second.resource_id).status == "inactive"
    _create(generic, {"lithology": first.resource_id})
    response = generic["client"].delete(
        f"/api/agent/workflow-uploads/{first.id}/",
        HTTP_X_PROJECT_ID=str(generic["project"].id),
    )
    assert response.status_code == 409


def test_confirmed_mapping_builds_inputs_for_multi_element_operators(generic):
    from apps.agent.geology_generic import prepare_generic
    from apps.agent.geology_multi import ROLES as MULTI_ROLES
    from apps.compute.data import candidate

    upload = store_upload(
        generic["owner"], generic["project"].id, geojson(), generic["batch"]
    )
    workflow = _create(generic, {"lithology": upload.resource_id})
    prepare_demo(workflow, generic["owner"], generic["policy"])
    workflow.refresh_from_db()
    confirm_demo(
        workflow,
        generic["owner"],
        generic["policy"],
        workflow.plan_hash,
        field_mapping={"lithology": {"name": "DCMC", "geo_sym": "DH"}},
    )
    workflow = AgentWorkflow.objects.get(pk=workflow.pk)
    assert prepare_generic(workflow, generic["owner"], generic["policy"]) is False
    inputs = workflow.plan["inputs"]
    assert set(inputs) == set(MULTI_ROLES)
    assert inputs["rules"] == generic["rules"].id
    assert workflow.parameters == {"working_epsg": 32647, "segment": "lithology"}
    lithology = DataResource.objects.get(pk=inputs["lithology"])
    assert set(candidate(lithology)["fields"]) == {"feature_id", "name", "geo_sym"}
    renderer = lithology.default_visualization["symbolization"]["renderer"]
    assert renderer["field"] == "name"
    assert [item["label"] for item in renderer["classes"]] == sorted(
        {"八宝山组二段", "闹仓坚沟组一段", "全新统冲积物"}
    )
    faults = DataResource.objects.get(pk=inputs["faults"])
    assert (
        faults.item_count == 0 and "LineString" in candidate(faults)["geometryTypes"][0]
    )
    assert len({inputs[m] for m in ("hematite", "chlorite", "dolomite")}) == 1
    placeholder = DataResource.objects.get(pk=inputs["hematite"])
    assert placeholder.owner_only and candidate(placeholder)["bands"] == 1
    assert "hematite" in workflow.plan["missingRoles"]
    original = DataResource.objects.get(pk=upload.resource_id)
    assert "DCMC" in candidate(original)["fields"]
    # A second pass must not create a second set of copies.
    count = DataResource.objects.count()
    prepare_generic(workflow, generic["owner"], generic["policy"])
    assert DataResource.objects.count() == count


def test_resource_limit_is_checked_before_field_review(generic):
    from apps.agent.models import AgentPolicy

    upload = store_upload(
        generic["owner"], generic["project"].id, geojson(), generic["batch"]
    )
    # Lithology alone still runs on three copies, a stand-in raster and the rules.
    AgentPolicy.objects.update(value={**generic["policy"], "maxResources": 4})
    with pytest.raises(ComputeError, match="资源上限"):
        _create(generic, {"lithology": upload.resource_id})
    AgentPolicy.objects.update(value={**generic["policy"], "maxResources": 5})
    assert _create(generic, {"lithology": upload.resource_id}).plan["uploadInputs"]


def test_failed_input_build_leaves_no_active_copies(generic, monkeypatch):
    from apps.agent import generic_inputs
    from apps.agent.geology_generic import prepare_generic

    upload = store_upload(
        generic["owner"], generic["project"].id, geojson(), generic["batch"]
    )
    workflow = _create(generic, {"lithology": upload.resource_id})
    prepare_demo(workflow, generic["owner"], generic["policy"])
    workflow.refresh_from_db()
    confirm_demo(
        workflow,
        generic["owner"],
        generic["policy"],
        workflow.plan_hash,
        field_mapping={"lithology": {"name": "DCMC"}},
    )
    workflow = AgentWorkflow.objects.get(pk=workflow.pk)

    def broken(*args, **kwargs):
        raise ComputeError("栅格写入失败")

    monkeypatch.setattr(generic_inputs, "placeholder_raster", broken)
    with pytest.raises(ComputeError, match="栅格写入失败"):
        prepare_generic(workflow, generic["owner"], generic["policy"])
    marker = f"workflow-working:{workflow.id}:"
    copies = DataResource.objects.filter(source__startswith=marker)
    assert copies.count() == 3
    assert not copies.filter(status="active").exists()


def test_raster_upload_is_private_from_import_and_off_the_layer_list(generic):
    import io

    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    from apps.raster.services import catalog_sync

    buffer = io.BytesIO()
    with rasterio.open(
        buffer,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(97.0, 35.61, 0.001, 0.001),
    ) as target:
        target.write(np.ones((1, 4, 4), dtype="uint8"))
    seen = []
    original = catalog_sync.DataResource.objects.update_or_create

    def record(*args, defaults=None, **kwargs):
        seen.append(dict(defaults or {}))
        return original(*args, defaults=defaults, **kwargs)

    catalog_sync.DataResource.objects.update_or_create = record
    try:
        upload = store_upload(
            generic["owner"],
            generic["project"].id,
            SimpleUploadedFile("hematite.tif", buffer.getvalue(), "image/tiff"),
            generic["batch"],
        )
    finally:
        catalog_sync.DataResource.objects.update_or_create = original
    assert upload.role_hint == "hematite"
    # The resource is written owner-only with the task source in one step.
    assert seen[-1]["owner_only"] is True
    assert seen[-1]["source"] == "workflow-upload:" + generic["batch"]
    layers = generic["client"].get(
        "/api/layers/", HTTP_X_PROJECT_ID=str(generic["project"].id)
    )
    assert upload.resource_id not in [
        item.get("dataResourceId") for item in layers.json()["items"]
    ]
    assert all(item["name"] != "hematite" for item in layers.json()["items"])
