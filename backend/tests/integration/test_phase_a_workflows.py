from types import SimpleNamespace
from unittest.mock import patch
from datetime import timedelta

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point
from django.urls import resolve
from django.utils import timezone

from apps.agent.demo_workflow import _collect_stage
from apps.agent.generic_inputs import (
    LITHOLOGY_COLORS,
    PALETTE,
    name_symbolization,
    style_lithology,
)
from apps.agent.geology_multi import VISIBLE_OUTPUTS, graph
from apps.agent.models import AgentWorkflow, AgentWorkflowStep
from apps.catalog.models import DataResource
from apps.compute.data import preview
from apps.compute.models import ComputeOutput, ComputeTask
from apps.compute.packages import ComputeError, checksum
from apps.compute.worker import clean_expired
from apps.core.storage import app_path
from apps.projects.context import ProjectScope, project_scope
from tests.integration.test_compute import setup_compute as setup_compute
from tests.integration.test_agent import setup_agent as setup_agent

pytestmark = pytest.mark.django_db

OUTPUT_KEYS = {
    "check": [
        "issues",
        "alterations",
        "statistics",
        "lithology_issues",
        "fault_issues",
        "alteration_issues",
    ],
    "apply": [
        "lithology",
        "faults",
        "alterations",
        "changes",
        "statistics",
        "changes_lithology_issues",
        "changes_fault_issues",
        "changes_alteration_issues",
    ],
    "recheck": [
        "issues",
        "alterations",
        "statistics",
        "lithology_issues",
        "fault_issues",
        "alteration_issues",
    ],
    "relations": ["before_intersections", "intersections", "statistics"],
    "prospect": ["before_zones", "after_zones", "evidence", "statistics"],
}
TABLE_KEYS = {"issues", "changes", "evidence", "statistics"}


@pytest.mark.parametrize(
    "scenario", ["geology_generic", "geology_multi_element_reasoning"]
)
def test_collect_only_nine_user_outputs_and_keep_all_task_results(
    setup_compute, scenario
):
    env = setup_compute
    scope = ProjectScope((env["project"].id,), env["project"].id, env["owner"].id)
    with project_scope(scope):
        workflow = AgentWorkflow.objects.create(
            owner=env["owner"],
            workflow_type=scenario,
            model="mock",
            import_results=True,
            plan={
                "inputs": {
                    "lithology": env["resource"].id,
                    "faults": env["resource"].id,
                },
                "stages": [],
                "stageIndex": 0,
            },
        )
        imported = []

        def register(user, output, **options):
            imported.append((output.task.name, output.key))
            resource = DataResource.objects.create(
                name=options["name"],
                code=f"phase-a-{output.id}",
                data_type=output.kind,
                maintainer=user,
            )
            return SimpleNamespace(status="ready", resource_id=resource.id)

        with (
            patch(
                "apps.agent.demo_workflow._authorize", return_value=(env["owner"], {})
            ),
            patch("apps.agent.demo_workflow.authorize_demo"),
            patch("apps.agent.demo_workflow.require_automatic_quality"),
            patch(
                "apps.agent.demo_workflow.request_output_import", side_effect=register
            ),
            patch(
                "apps.agent.demo_workflow.resolve_resource",
                side_effect=lambda user, policy, identity: DataResource.objects.get(
                    pk=identity
                ),
            ),
            patch(
                "apps.agent.demo_workflow.read_results",
                side_effect=lambda workflow, user, policy, task: [
                    {"outputId": output.id, "key": output.key}
                    for output in task.outputs.all()
                ],
            ),
            patch("apps.agent.generic_inputs.style_lithology") as color,
        ):
            for name, keys in OUTPUT_KEYS.items():
                task = ComputeTask.objects.create(
                    owner=env["owner"],
                    version=env["version"],
                    name=name,
                    status="succeeded",
                    idempotency_key=name,
                )
                for key in keys:
                    ComputeOutput.objects.create(
                        task=task,
                        key=key,
                        label=key,
                        kind="table" if key in TABLE_KEYS else "vector",
                        file_name=key,
                        path=key,
                        size_bytes=0,
                        checksum="a" * 64,
                    )
                stage = {
                    "name": name,
                    "bindings": {},
                    "status": "running",
                    "taskId": str(task.id),
                }
                workflow.plan["stages"].append(stage)
                assert _collect_stage(workflow, env["owner"], {}, stage, task)
                assert {
                    output["key"] for output in stage["outputs"]
                } == VISIBLE_OUTPUTS[name]
                assert len(stage["results"]) == len(keys)
            assert color.call_count == 1
        assert len(imported) == len(workflow.result_resource_ids) == 9
        assert len(workflow.result_ids) == 27
        ComputeOutput.objects.filter(pk__in=workflow.result_ids).update(
            created_at=timezone.now() - timedelta(days=8)
        )
        clean_expired(force=True)
        assert not ComputeOutput.objects.filter(
            pk__in=workflow.result_ids, expired=True
        ).exists()
        assert imported == [
            (stage, key)
            for stage, keys in OUTPUT_KEYS.items()
            for key in keys
            if key in VISIBLE_OUTPUTS[stage]
        ]
        for _, _, bindings in graph():
            for binding in bindings.values():
                if "/" in binding:
                    origin, key = binding.split("/", 1)
                    assert key in VISIBLE_OUTPUTS[origin]
        output_ids = list(workflow.result_ids)
        workflow.delete()
        clean_expired(force=True)
        assert (
            ComputeOutput.objects.filter(pk__in=output_ids, expired=True).count() == 27
        )


@pytest.mark.parametrize(
    "scenario", ["geology_generic", "geology_multi_element_reasoning"]
)
def test_card_is_small_and_never_leaks_large_nested_details(setup_agent, scenario):
    env = setup_agent
    stages = [
        {
            "name": name,
            "status": "completed",
            "taskId": "67ac90d1-999f-44b7-9b68-1da1f726a142",
            "outputs": [
                {
                    "outputId": index + 1,
                    "key": key,
                    "label": key,
                    "kind": "table" if key in TABLE_KEYS else "vector",
                    "resourceId": index + 100,
                    "checksum": "a" * 64,
                    "resourceRevision": "2026-11-04T08:00:00Z",
                }
                for index, key in enumerate(keys)
                if key in VISIBLE_OUTPUTS[name]
            ],
        }
        for name, keys in OUTPUT_KEYS.items()
    ]
    stages[0].update(
        modelAttempts=[{"request": "x" * 500_000}], results=[{"rows": "x" * 300_000}]
    )
    with project_scope(env["scope"]):
        workflow = AgentWorkflow.objects.create(
            owner=env["user"],
            model="mock",
            workflow_type=scenario,
            status="succeeded",
            plan={
                "phase": "completed",
                "stages": stages,
                "finalStage": {"modelAttempts": "x" * 200_000},
                "modificationReview": {"suggestions": "x" * 300_000},
            },
            evidence=[{"content": "x" * 50_000}],
        )
        AgentWorkflowStep.objects.create(
            workflow=workflow,
            sequence=1,
            kind="model",
            status="succeeded",
            action={"response": "x" * 300_000},
        )
    url = f"/api/agent/workflows/{workflow.id}/"
    resolve(url)
    with patch("apps.agent.workflow.authorize_workflow_history") as authorize:
        full = env["client"].get(url, **env["header"])
        card = env["client"].get(url + "?view=card", **env["header"])
        assert authorize.call_count == 2
    assert full.status_code == card.status_code == 200
    data = card.json()
    assert data["view"] == "card" and data["stepCount"] == 1
    assert data["steps"] == data["evidence"] == []
    assert (
        not {"modificationReview", "finalStage", "modelAttempts", "results"}
        & data["plan"].keys()
    )
    assert "modelAttempts" not in card.content.decode()
    assert "modificationReview" not in data
    assert "modificationReview" in full.json()
    assert len(card.content) < 5000
    assert len(card.content) < len(full.content) / 100
    print(f"{scenario}: full={len(full.content)}, card={len(card.content)}")
    bad = env["client"].get(url + "?view=unknown", **env["header"])
    assert bad.status_code == 400 and "detail" in bad.json()


def test_lithology_colors_match_38_cim_names_and_fallback_and_profile(setup_compute):
    assert len(LITHOLOGY_COLORS) == 38
    assert LITHOLOGY_COLORS["全新世冲积物qhal"] == "#ffffd8"
    data = pd.DataFrame(
        {"name": ["全新世冲积物qhal", "未知新单元", "全新世冲积物qhal"]}
    )
    classes = name_symbolization(data)["renderer"]["classes"]
    colors = {item["value"]: item["color"] for item in classes}
    assert colors["全新世冲积物qhal"] == "#ffffd8"
    assert colors["未知新单元"] in PALETTE
    assert all(item["value"] == item["label"] for item in classes)
    env = setup_compute
    resource = env["resource"]
    with patch("geopandas.read_file", return_value=data):
        style_lithology(resource)
    resource.refresh_from_db()
    assert (
        resource.default_visualization["symbolization"]["renderer"]["field"] == "name"
    )
    response = env["client"].get(
        f"/api/catalog/resources/{resource.id}/profile/",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )
    assert response.status_code == 200, response.content
    assert response.json()["defaultVisualization"] == resource.default_visualization


def test_map_preview_reads_full_checked_vector_without_import(setup_compute):
    env = setup_compute
    path = app_path("phase-a/intersections.gpkg")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = gpd.GeoDataFrame(
        {"name": [str(index) for index in range(101)]},
        geometry=[Point(97, 35)] * 101,
        crs=4326,
    )
    frame.to_file(path, layer="intersections", driver="GPKG")
    output = SimpleNamespace(
        path="phase-a/intersections.gpkg",
        kind="vector",
        metadata={"layer": "intersections"},
        checksum=checksum(path),
    )
    count = DataResource.objects.count()
    result = preview(output, "map")
    assert len(result["geojson"]["features"]) == 101
    assert result["geojson"]["features"][0]["geometry"]["coordinates"] == [97, 35]
    assert DataResource.objects.count() == count
    with project_scope(
        ProjectScope((env["project"].id,), env["project"].id, env["owner"].id)
    ):
        task = ComputeTask.objects.create(
            owner=env["owner"],
            version=env["version"],
            name="未入库交汇",
            status="succeeded",
            idempotency_key="phase-a-map",
        )
        stored = ComputeOutput.objects.create(
            task=task,
            key="before_intersections",
            kind="vector",
            label="修正前交汇",
            path=output.path,
            file_name="intersections.gpkg",
            size_bytes=path.stat().st_size,
            checksum=output.checksum,
            metadata=output.metadata,
        )
    url = f"/api/compute/outputs/{stored.id}/preview/"
    header = {"HTTP_X_PROJECT_ID": str(env["project"].id)}
    response = env["client"].get(url + "?view=map", **header)
    assert response.status_code == 200, response.content
    assert len(response.json()["geojson"]["features"]) == 101
    assert len(env["client"].get(url, **header).json()["rows"]) == 100
    assert env["client"].get(url + "?view=unknown", **header).status_code == 400
    env["client"].force_login(env["outsider"])
    assert env["client"].get(url + "?view=map", **header).status_code in {403, 404}
    env["client"].force_login(env["owner"])
    assert DataResource.objects.count() == count
    output.checksum = "0" * 64
    with pytest.raises(ComputeError, match="内容已变化"):
        preview(output, "map")
    output.checksum = checksum(path)
    with patch("geopandas.read_file", return_value=pd.DataFrame(index=range(30001))):
        with pytest.raises(ComputeError, match="超过30000"):
            preview(output, "map")
    assert (
        env["client"]
        .get(
            "/api/compute/outputs/999999/preview/?view=map",
            HTTP_X_PROJECT_ID=str(env["project"].id),
        )
        .status_code
        == 404
    )
