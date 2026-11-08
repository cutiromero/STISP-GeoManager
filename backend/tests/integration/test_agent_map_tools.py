"""Real data references and private map writes; no original bytes are modified."""

import hashlib
import json
from copy import deepcopy

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from rasterio.transform import from_origin
from shapely.geometry import box

from apps.agent.models import AgentPolicy
from apps.agent.platform_actions import platform_actions
from apps.agent.policy import default_policy
from apps.agent.tools import execute, evidence_items
from apps.catalog.models import DataResource, WorkspaceScene
from apps.catalog.views import _snapshot_contains_embedded_data
from apps.core.storage import (
    vector_geopackage_path,
    raster_processed_path,
    raster_source_path,
)
from apps.projects.context import ProjectScope, project_scope
from apps.raster.models import RasterDataset
from tests.integration.test_agent import new_run, setup_agent  # noqa: F401


@pytest.fixture
def mapped(setup_agent):  # noqa: F811
    env = setup_agent
    env["user"].user_permissions.add(
        *Permission.objects.filter(
            codename__in=[
                "load_vector_layer",
                "load_raster_layer",
                "custom_symbolization",
                "add_workspacescene",
                "view_workspacescene",
            ]
        )
    )
    with project_scope(env["scope"]):
        path = vector_geopackage_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        gpd.GeoDataFrame(
            {"name": ["岩性A", "岩性A", "岩性B"], "class": [1, 1, 2]},
            geometry=[
                box(95, 35, 95.1, 35.1),
                box(95.1, 35, 95.2, 35.1),
                box(95.2, 35, 95.3, 35.1),
            ],
            crs=4326,
        ).to_file(path, layer="rocks", driver="GPKG")
        env["vector"] = DataResource.objects.create(
            name="区域岩性",
            code="registered-rocks",
            data_type="vector",
            file_format="GPKG",
            storage_path="rocks",
            coordinate_system="EPSG:4326",
        )
        env["file"] = path
    return env


def call(run, name, args):
    result, pairs = execute(run, name, args)
    run.evidence += evidence_items(run, name, pairs)
    run.save(update_fields=["evidence"])
    return result


def recipe(resource):
    return {
        "resourceIds": [resource.id],
        "name": "岩性分类地图",
        "styles": [
            {
                "resourceId": resource.id,
                "mode": "unique",
                "field": "name",
                "classes": [
                    {"value": "岩性A", "color": "#e5bf76"},
                    {"value": "岩性B", "color": "#80a6c7"},
                ],
            }
        ],
    }


def test_real_categories_and_idempotent_personal_map_keep_original_data(mapped):
    env = mapped
    with project_scope(env["scope"]):
        run = new_run(env)
        original = hashlib.sha256(env["file"].read_bytes()).hexdigest()
        stamp = env["vector"].updated_at
        profile = call(run, "get_map_data_profile", {"resourceId": env["vector"].id})
        assert profile["categoriesComplete"] and profile["categoryField"] == "name"
        assert (
            profile["categories"][0]["count"] == 2
            and profile["categories"][1]["count"] == 1
        )
        first = call(run, "prepare_map_workspace", recipe(env["vector"]))
        second = call(run, "prepare_map_workspace", recipe(env["vector"]))
        assert (
            first["workspaceId"] == second["workspaceId"]
            and WorkspaceScene.objects.count() == 1
        )
        scene = WorkspaceScene.objects.get(pk=first["workspaceId"])
        assert scene.owner_id == env["user"].id and not scene.access_groups.exists()
        assert not _snapshot_contains_embedded_data(scene.snapshot)
        renderer = scene.snapshot["groups"][0]["children"][0]["symbolization"][
            "renderer"
        ]
        assert renderer["classes"][0]["values"] == ["岩性A"]
        assert (
            platform_actions(run, env["user"], default_policy())[0]["sceneId"]
            == scene.id
        )
        env["vector"].refresh_from_db()
        assert (
            env["vector"].updated_at == stamp
            and env["vector"].default_visualization == {}
        )
        assert hashlib.sha256(env["file"].read_bytes()).hexdigest() == original


def test_actions_are_serialized_only_for_real_owned_same_project_scenes(mapped):
    from django.test import Client
    from apps.projects.models import Project

    env = mapped
    with project_scope(env["scope"]):
        run = new_run(env)
        result = call(run, "prepare_map_workspace", {"resourceIds": [env["vector"].id]})
        scene = WorkspaceScene.objects.get(pk=result["workspaceId"])
        client = Client()
        client.force_login(env["user"])
        response = client.get(
            f"/api/agent/runs/{run.id}/", HTTP_X_PROJECT_ID=str(env["project"].id)
        )
        assert response.status_code == 200
        assert response.json()["run"]["platformActions"][0]["sceneId"] == scene.id
        scene.owner = env["other"]
        scene.save(update_fields=["owner"])
        assert platform_actions(run, env["user"], default_policy()) == []
        other_project = Project.objects.create(code="other-map", name="Other")
        with project_scope(
            ProjectScope((other_project.id,), other_project.id, env["user"].id)
        ):
            foreign_scene = WorkspaceScene.objects.create(
                owner=env["user"],
                name="Other map",
                kind="project",
                project_tag=other_project,
                snapshot={},
            )
        run.evidence[0]["result"]["workspaceId"] = foreign_scene.id
        assert platform_actions(run, env["user"], default_policy()) == []


@pytest.mark.parametrize(
    "change",
    [
        {"geometry": {}},
        {"classes": [{"value": "不存在", "color": "#ffffff"}]},
        {"classes": [{"value": "岩性A", "color": "#e5bf76"}]},
        {"color": "url(javascript:1)"},
        {"opacity": True},
    ],
)
def test_invalid_or_data_edit_arguments_never_create_a_scene(mapped, change):
    with project_scope(mapped["scope"]):
        run = new_run(mapped)
        call(run, "get_map_data_profile", {"resourceId": mapped["vector"].id})
        args = recipe(mapped["vector"])
        args["styles"][0].update(change)
        with pytest.raises(ValidationError):
            call(run, "prepare_map_workspace", args)
        assert not WorkspaceScene.objects.exists()


def test_category_style_requires_real_current_profile(mapped):
    with project_scope(mapped["scope"]):
        run = new_run(mapped)
        with pytest.raises(ValidationError, match="先调用get_map_data_profile"):
            call(run, "prepare_map_workspace", recipe(mapped["vector"]))
        with pytest.raises(ValidationError, match="真实字段"):
            call(
                run,
                "get_map_data_profile",
                {
                    "resourceId": mapped["vector"].id,
                    "field": 'name";DROP TABLE rocks;--',
                },
            )


def test_manual_scope_privacy_and_permission_revocation(mapped):
    env = mapped
    with project_scope(env["scope"]):
        run = new_run(env)
        run.resource_ids = [env["resource"].id]
        with pytest.raises(PermissionDenied):
            call(run, "get_map_data_profile", {"resourceId": env["vector"].id})
        run.resource_ids = []
        call(run, "get_map_data_profile", {"resourceId": env["vector"].id})
        call(run, "prepare_map_workspace", recipe(env["vector"]))
        env["vector"].owner_only = True
        env["vector"].maintainer = env["other"]
        env["vector"].save()
        assert platform_actions(run, env["user"], default_policy()) == []
        with pytest.raises(PermissionDenied):
            call(run, "get_map_data_profile", {"resourceId": env["vector"].id})


def test_display_tool_policy_is_independent_from_compute_but_can_be_disabled(mapped):
    with project_scope(mapped["scope"]):
        run = new_run(mapped)
        assert not default_policy()["operatorEnabled"]
        result = call(
            run, "prepare_map_workspace", {"resourceIds": [mapped["vector"].id]}
        )
        assert result["workspaceId"] and not result["originalDataChanged"]
        policy = default_policy()
        policy["mapDisplayEnabled"] = False
        AgentPolicy.objects.update_or_create(pk=1, defaults={"value": policy})
        with pytest.raises(PermissionDenied):
            call(run, "prepare_map_workspace", {"resourceIds": [mapped["vector"].id]})


def test_navigation_only_uses_fixed_project_bound_destinations(mapped):
    with project_scope(mapped["scope"]):
        run = new_run(mapped)
        value = call(run, "get_platform_link", {"page": "compute"})
        assert value["url"] == f"/compute?projectTagId={mapped['project'].id}"
        with pytest.raises(ValidationError):
            call(run, "get_platform_link", {"page": "https://example.com"})
        with pytest.raises(ValidationError):
            call(
                run, "get_platform_link", {"page": "map", "url": "https://example.com"}
            )


def test_raster_color_table_is_stored_in_map_and_never_written_to_source(mapped):
    env = mapped
    with project_scope(env["scope"]):
        path = raster_processed_path("mineral.tif")
        path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=2,
            width=2,
            count=1,
            dtype="uint8",
            crs=4326,
            transform=from_origin(95, 36, 0.1, 0.1),
        ) as stream:
            stream.write(np.array([[0, 1], [1, 0]], dtype="uint8"), 1)
        source = raster_source_path("mineral.tif")
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(path.read_bytes())
        resource = DataResource.objects.create(
            name="矿物识别",
            code="registered-mineral",
            data_type="raster",
            file_format="GTiff",
            storage_path="mineral.tif",
        )
        info = {
            "size": [2, 2],
            "bands": [{"band": 1, "type": "Byte", "minimum": 0, "maximum": 1}],
        }
        dataset = RasterDataset.objects.create(
            data_resource=resource,
            name=resource.name,
            code=resource.code,
            source_relative_path="mineral.tif",
            processed_relative_path="mineral.tif",
            raster_kind="categorical",
            source_gdalinfo=info,
            processed_gdalinfo=info,
            band_count=1,
            status="ready",
            bounds_4326=[95, 35.8, 95.2, 36],
        )
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        run = new_run(env)
        profile = call(run, "get_map_data_profile", {"resourceId": resource.id})
        assert profile["categoriesComplete"] and len(profile["categories"]) == 2
        value = call(
            run,
            "prepare_map_workspace",
            {
                "resourceIds": [resource.id],
                "styles": [
                    {
                        "resourceId": resource.id,
                        "mode": "unique",
                        "band": 1,
                        "classes": [
                            {"value": 0, "color": "#00000000"},
                            {"value": 1, "color": "#cb6139ff"},
                        ],
                    }
                ],
            },
        )
        layer = WorkspaceScene.objects.get(pk=value["workspaceId"]).snapshot["groups"][
            0
        ]["children"][0]
        assert (
            layer["symbolization"]["mode"] == "unique"
            and layer["symbolization"]["uniqueValues"][1]["color"] == "#cb6139ff"
        )
        dataset.refresh_from_db()
        resource.refresh_from_db()
        assert dataset.default_rules == {} and resource.default_visualization == {}
        assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_worker_can_finish_real_map_tools_without_looking_for_a_compute_algorithm(
    mapped, monkeypatch
):
    from apps.agent import worker

    env = mapped
    commands = iter(
        [
            {
                "action": "get_map_data_profile",
                "arguments": {"resourceId": env["vector"].id},
            },
            {"action": "prepare_map_workspace", "arguments": recipe(env["vector"])},
            {"action": "final", "answer": "已准备个人地图，点击下方按钮查看。[证据 2]"},
        ]
    )

    def respond(*args, **kwargs):
        yield json.dumps(next(commands), ensure_ascii=False)

    monkeypatch.setattr(worker, "stream", respond)
    monkeypatch.setattr(worker, "model_window", lambda model: 32768)
    monkeypatch.setattr(worker, "prepare_context", lambda *args: (1, False))
    with project_scope(env["scope"]):
        run = new_run(env)
        run.prompt = "给区域岩性配色，在地理工作台展示"
        run.save(update_fields=["prompt"])
    worker.run_task(run.id)
    run.refresh_from_db()
    assert run.status == "succeeded", run.detail
    assert "已准备个人地图" in run.answer
    assert [item["tool"] for item in run.evidence] == [
        "get_map_data_profile",
        "prepare_map_workspace",
    ]


def test_reference_profile_and_saved_scene_refresh_share_one_live_color_table(
    mapped, monkeypatch, tmp_path
):
    from apps.agent import color_library

    env = mapped
    value = "全新世冲积物qhal"
    path = tmp_path / "lithology_colors.json"
    palette = json.loads(color_library.LITHOLOGY_PATH.read_bytes())
    path.write_text(json.dumps(palette))
    monkeypatch.setattr(color_library, "LITHOLOGY_PATH", path)
    with project_scope(env["scope"]):
        frame = gpd.read_file(env["file"], layer="rocks")
        frame["name"] = value
        frame.to_file(env["file"], layer="rocks", driver="GPKG")
        original = hashlib.sha256(env["file"].read_bytes()).hexdigest()
        run = new_run(env)
        profile = call(run, "get_map_data_profile", {"resourceId": env["vector"].id})
        assert profile["categories"][0]["suggestedColor"] == "#ffffd8"
        assert profile["categories"][0]["colorLocked"]
        result = call(
            run,
            "prepare_map_workspace",
            {
                "resourceIds": [env["vector"].id],
                "styles": [
                    {
                        "resourceId": env["vector"].id,
                        "mode": "reference",
                        "field": "name",
                    }
                ],
            },
        )
        assert result["layers"][0]["libraryClassCount"] == 1
        scene = WorkspaceScene.objects.get(pk=result["workspaceId"])
        stored = deepcopy(scene.snapshot)
        palette["colors"][value] = "#123456"
        path.write_text(json.dumps(palette))
        response = env["client"].get(
            f"/api/catalog/workspaces/{scene.id}/", **env["header"]
        )
        assert response.status_code == 200
        style = response.json()["snapshot"]["groups"][0]["children"][0]["symbolization"]
        assert style["renderer"]["classes"][0]["color"] == "#123456"
        scene.refresh_from_db()
        assert scene.snapshot == stored
        assert hashlib.sha256(env["file"].read_bytes()).hexdigest() == original
