"""Actual input files are checked before queueing or model/compute work."""

# ruff: noqa: F811
import csv
import json
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point, box

from apps.agent.demo_workflow import advance_demo, prepare_demo
from apps.agent.geology_input_validation import ROLES, validate_geology_inputs
from apps.agent.models import AgentWorkflow
from apps.catalog.models import DataResource
from apps.compute.models import AlgorithmResource, AlgorithmVersion, ComputeTask
from apps.core.storage import table_data_path, vector_geopackage_path
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo  # noqa: F401

pytestmark = pytest.mark.django_db


def write_vector(resource, role, *, geometry=None, crs="EPSG:4326", omit=()):
    fields = ROLES[role][2] - set(omit)
    values = {key: key + "_value" for key in fields}
    path = vector_geopackage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(
        [values],
        geometry=[geometry if geometry is not None else box(94, 35, 94.01, 35.01)],
        crs=crs,
    ).to_file(path, layer=resource.storage_path, driver="GPKG")


@pytest.fixture
def geological_inputs(demo):
    env = demo
    inputs = {}
    for role in ROLES:
        resource = DataResource.objects.create(
            name=role,
            code="validation-" + role,
            data_type="table" if role == "rules" else "vector",
            storage_path="table/review-rules.csv"
            if role == "rules"
            else "review_" + role,
            file_format="CSV" if role == "rules" else "GPKG",
            coordinate_system="EPSG:4326",
            maintainer=env["owner"],
        )
        inputs[role] = resource.id
        if role != "rules":
            write_vector(resource, role)
    rules_path = table_data_path("review-rules.csv")
    with rules_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=sorted(ROLES["rules"][2]))
        writer.writeheader()
        writer.writerow({key: key + "_value" for key in ROLES["rules"][2]})
    for identifier in ("geology-map-check", "geology-map-correct"):
        manifest_path = (
            Path(__file__).resolve().parents[3]
            / "examples"
            / "compute"
            / identifier
            / "operator.yaml"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for spec in manifest["inputs"]:
            spec.setdefault("required", True)
        algorithm = AlgorithmResource.objects.create(
            identifier=identifier,
            name=manifest["name"],
            created_by=env["owner"],
        )
        AlgorithmVersion.objects.create(
            algorithm=algorithm,
            status="published",
            version=manifest["version"],
            manifest=manifest,
            checksum="c" * 64,
            runtime_digest="sha256:" + "a" * 64,
        )
    env["validationInputs"] = inputs
    env["validationBody"] = {
        "workflowType": "geology_map_review",
        "goal": "检查当前地质图并形成修改建议",
        "model": "mock",
        "inputs": inputs,
        "resourceIds": list(inputs.values()),
        "parameters": {},
        "idempotencyKey": "validate-geology-inputs",
        "knowledgeSelection": {"mode": "manual", "domains": ["geology"]},
    }
    yield env


def post(env, body=None):
    return env["client"].post(
        "/api/agent/workflows/",
        json.dumps(body or env["validationBody"]),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )


def assert_rejected(env, expected, body=None):
    with (
        patch("apps.agent.demo_decisions.decide") as model,
        patch("apps.agent.demo_workflow.submit") as compute,
    ):
        response = post(env, body)
    assert response.status_code == 400, response.content
    assert expected in response.json()["detail"]
    assert not AgentWorkflow.objects.exists()
    assert not ComputeTask.objects.exists()
    model.assert_not_called()
    compute.assert_not_called()


def test_actual_polygon_and_rule_files_create_a_plan_request(geological_inputs):
    env = geological_inputs
    info = validate_geology_inputs(
        env["owner"], env["policy"], env["validationInputs"], {}
    )
    assert info["initial_map"]["geometryTypes"] == ["Polygon"]
    assert info["initial_map"]["crs"] == "EPSG:4326"
    response = post(env)
    assert response.status_code == 202, response.content
    workflow = AgentWorkflow.objects.get(pk=response.json()["id"])
    prepare_demo(workflow, env["owner"], env["policy"])
    assert workflow.status == "waiting_approval"
    assert workflow.plan["stages"][1]["parameters"]["working_epsg"] == 32646
    assert not ComputeTask.objects.exists()


@pytest.mark.parametrize(
    "role,other,expected",
    [
        ("initial_map", "coverage", "待检查地质图缺少必要字段"),
        ("coverage", "initial_map", "制图覆盖范围与例外缺少必要字段"),
        ("rules", "initial_map", "专家规则须选择规则表格"),
        ("initial_map", "rules", "待检查地质图须选择面矢量数据"),
        ("coverage", "rules", "制图覆盖范围与例外须选择面矢量数据"),
    ],
)
def test_wrong_role_is_rejected_before_creating_workflow(
    geological_inputs, role, other, expected
):
    env = geological_inputs
    original = DataResource.objects.get(pk=env["validationInputs"][other])
    copy = DataResource.objects.create(
        name="wrong role",
        code="wrong-role",
        data_type=original.data_type,
        storage_path=original.storage_path,
        file_format=original.file_format,
        maintainer=env["owner"],
    )
    body = {
        **env["validationBody"],
        "inputs": {**env["validationInputs"], role: copy.id},
        "resourceIds": [*env["validationInputs"].values(), copy.id],
    }
    assert_rejected(env, expected, body)


@pytest.mark.parametrize(
    "role,field",
    [
        ("initial_map", "feature_id"),
        ("coverage", "coverage_id"),
        ("rules", "evidence_id"),
    ],
)
def test_actual_files_missing_required_fields_are_rejected(
    geological_inputs, role, field
):
    env = geological_inputs
    resource = DataResource.objects.get(pk=env["validationInputs"][role])
    if role == "rules":
        table_data_path("review-rules.csv").write_text(
            "rule_id\nr1\n", encoding="utf-8"
        )
    else:
        write_vector(resource, role, omit={field})
    assert_rejected(env, field)


@pytest.mark.parametrize("role", ["initial_map", "coverage"])
@pytest.mark.parametrize(
    "geometry,label",
    [(Point(94, 35), "Point"), (LineString([(94, 35), (94.01, 35.01)]), "LineString")],
)
def test_actual_non_polygon_geometry_is_rejected(
    geological_inputs, role, geometry, label
):
    env = geological_inputs
    write_vector(
        DataResource.objects.get(pk=env["validationInputs"][role]),
        role,
        geometry=geometry,
    )
    assert_rejected(env, "实际为：" + label)


@pytest.mark.parametrize("role", ["initial_map", "coverage"])
def test_catalog_crs_does_not_hide_missing_file_crs(geological_inputs, role):
    env = geological_inputs
    resource = DataResource.objects.get(pk=env["validationInputs"][role])
    write_vector(resource, role, crs=None)
    assert resource.coordinate_system == "EPSG:4326"
    assert_rejected(env, ROLES[role][0] + "缺少有效坐标系")


@pytest.mark.parametrize("role", list(ROLES))
def test_unreadable_actual_input_has_a_role_specific_error(geological_inputs, role):
    env = geological_inputs
    resource = DataResource.objects.get(pk=env["validationInputs"][role])
    resource.storage_path = "table/missing.csv" if role == "rules" else "missing_layer"
    resource.save(update_fields=["storage_path"])
    assert_rejected(env, ROLES[role][0] + "的实际文件不可读")


def test_same_map_and_coverage_cannot_create_activity(geological_inputs):
    env = geological_inputs
    env["validationBody"]["inputs"]["coverage"] = env["validationInputs"]["initial_map"]
    assert_rejected(env, "不能选择同一份数据")


@pytest.mark.parametrize(
    "parameters,expected",
    [
        ({"working_epsg": 4326}, "须为米制投影"),
        ({"working_epsg": 2263}, "须为米制投影"),
        ({"working_epsg": 999999}, "EPSG 不存在"),
        ({"working_epsg": True}, "须为有效整数"),
        ({"max_changes": 0}, "本轮修改数量上限超出允许范围"),
        ({"max_changes": 1.5}, "本轮修改数量上限须为有效整数"),
        ({"max_gap_area_m2": -1}, "漏填筛查面积上限（平方米）超出允许范围"),
        ({"geometry_tolerance_m": 0.2}, "空间核对容差（米）超出允许范围"),
        ({"unrecognized": 1}, "包含未声明字段"),
    ],
)
def test_invalid_parameters_do_not_start_model_or_compute(
    geological_inputs, parameters, expected
):
    env = geological_inputs
    assert_rejected(env, expected, {**env["validationBody"], "parameters": parameters})


def test_worker_rechecks_files_changed_after_plan_request(geological_inputs):
    env = geological_inputs
    response = post(env)
    assert response.status_code == 202, response.content
    workflow = AgentWorkflow.objects.get(pk=response.json()["id"])
    write_vector(
        DataResource.objects.get(pk=env["validationInputs"]["initial_map"]),
        "initial_map",
        omit={"feature_id"},
    )
    with (
        patch("apps.agent.demo_workflow.search_entries") as search,
        patch("apps.agent.demo_workflow.decide") as model,
        patch("apps.agent.demo_workflow.submit") as compute,
    ):
        advance_demo(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "failed"
    assert "待检查地质图缺少必要字段：feature_id" in workflow.detail
    search.assert_not_called()
    model.assert_not_called()
    compute.assert_not_called()
    assert not ComputeTask.objects.exists()


def test_published_parameter_bounds_are_used(geological_inputs):
    env = geological_inputs
    version = AlgorithmVersion.objects.get(algorithm__identifier="geology-map-check")
    for spec in version.manifest["parameters"]:
        if spec["key"] == "max_changes":
            spec["max"] = 1
            spec["default"] = 1
    version.save(update_fields=["manifest"])
    assert_rejected(
        env,
        "本轮修改数量上限超出允许范围",
        {**env["validationBody"], "parameters": {"max_changes": 2}},
    )


def test_reference_materials_are_not_accepted(geological_inputs):
    env = geological_inputs
    resource = DataResource.objects.get(pk=env["validationInputs"]["initial_map"])
    resource.source = "geology-review-reference:independent-only"
    resource.save(update_fields=["source"])
    assert_rejected(env, "仅用于独立验收")
