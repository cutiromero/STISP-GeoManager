"""Authorized discovery, manual ceilings and synthetic-only defaults."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.agent.models import AgentRuntime
from apps.agent.research_presets import MARKERS, discover, list_demos
from apps.catalog.models import DataResource
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import ProjectMembership
from tests.integration.test_demo_workflow import demo  # noqa: F401
from tests.integration.test_compute import setup_compute  # noqa: F401

pytestmark = pytest.mark.django_db


def mark(env):
    examples = Path(__file__).resolve().parents[3] / "examples/compute"
    for directory in examples.iterdir():
        manifest_path = directory / "operator.yaml"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        version = env["versions"].get(manifest["identifier"])
        if version:
            version.manifest = manifest
            version.save()
    for role, (field, marker) in MARKERS.items():
        # Existing demo fixture shares tables. Give each discovery role a distinct resource.
        original = DataResource.objects.get(pk=env["inputs"][role])
        resource = DataResource.objects.create(
            code=marker,
            name="模拟 · " + role,
            data_type=original.data_type,
            source=marker if field == "source" else "模拟资料",
            maintainer=env["owner"],
        )
        env["inputs"][role] = resource.id
    DataResource.objects.create(
        code="demo-ecology-context-updated",
        name="模拟 · 新增观测",
        data_type="table",
        maintainer=env["owner"],
    )


def scene(catalog, scenario="ecology_investigation"):
    return next(s for s in catalog["scenarios"] if s["scenario"] == scenario)


def test_discovery_uses_markers_not_project_name_or_ids(demo):  # noqa: F811
    env = demo
    with project_scope(
        ProjectScope((env["project"].id,), env["project"].id, env["owner"].id)
    ):
        mark(env)
        result = scene(discover(env["owner"], env["policy"]))
        assert result["available"]
        assert result["preferredInputs"] == {
            role: env["inputs"][role] for role in result["inputs"]
        }
        assert result["defaults"]["red"] == 1
        assert result["defaults"]["nir"] == 2
        contexts = result["inputs"]["context"]
        assert len(contexts) == 2 and sum(item["isUpdate"] for item in contexts) == 1
        assert all(item["sourceNote"] and item["revision"] for item in contexts)


def test_hidden_and_unselected_resources_never_enter_catalog(demo):  # noqa: F811
    env = demo
    with project_scope(
        ProjectScope((env["project"].id,), env["project"].id, env["owner"].id)
    ):
        mark(env)
        hidden = DataResource.objects.get(pk=env["inputs"]["surveys"])
        hidden.owner_only, hidden.maintainer = True, env["outsider"]
        hidden.save()
        result = scene(discover(env["owner"], env["policy"]), "geology_correction")
        assert result["inputs"]["surveys"] == []
        assert not result["available"]
        selected = [env["inputs"]["initial_map"]]
        run = SimpleNamespace(
            resource_ids=selected,
            data_selection_mode="manual",
            algorithm_version_ids=[],
            algorithm_selection_mode="auto",
        )
        catalog = discover(env["owner"], env["policy"], run)
        identities = {
            i["id"]
            for s in catalog["scenarios"]
            for rows in s["inputs"].values()
            for i in rows
        }
        assert identities == set(selected)
        assert not scene(catalog)["available"]


def test_custom_images_do_not_inherit_demo_band_dates(demo):  # noqa: F811
    env = demo
    with project_scope(
        ProjectScope((env["project"].id,), env["project"].id, env["owner"].id)
    ):
        run = SimpleNamespace(
            resource_ids=[env["inputs"]["early_image"], env["inputs"]["late_image"]],
            data_selection_mode="manual",
            algorithm_version_ids=[],
            algorithm_selection_mode="auto",
        )
        result = scene(discover(env["owner"], env["policy"], run))
        assert not {"red", "nir", "early_date", "late_date"} & set(result["defaults"])
        assert all(
            "default" not in p
            for p in result["parameterSpecs"]
            if p["key"] in {"red", "nir"}
        )


def test_algorithm_manual_ceiling_and_disabled_version(demo):  # noqa: F811
    env = demo
    with project_scope(
        ProjectScope((env["project"].id,), env["project"].id, env["owner"].id)
    ):
        mark(env)
        version = env["versions"]["raster-ndvi"]
        run = SimpleNamespace(
            resource_ids=[],
            data_selection_mode="auto",
            algorithm_version_ids=[version.id],
            algorithm_selection_mode="manual",
        )
        result = scene(discover(env["owner"], env["policy"], run))
        assert [a["versionId"] for a in result["algorithms"]] == [version.id]
        assert not result["available"]
        version.manifest = {**version.manifest, "agent": {"enabled": False}}
        version.save()
        assert scene(discover(env["owner"], env["policy"], run))["algorithms"] == []


def test_directory_checks_membership_and_live_services(demo):  # noqa: F811
    env = demo
    with project_scope(
        ProjectScope((env["project"].id,), env["project"].id, env["owner"].id)
    ):
        mark(env)
    AgentRuntime.objects.update_or_create(
        name="worker", defaults={"heartbeat": timezone.now()}
    )
    AgentRuntime.objects.update_or_create(
        name="workflow-worker", defaults={"heartbeat": timezone.now()}
    )
    with patch(
        "apps.agent.research_presets.visible_models",
        return_value=[{"status": "online"}],
    ):
        items = list_demos(env["owner"], env["policy"])["items"]
        assert {i["projectId"] for i in items} == {env["project"].id}
        assert all(i["available"] for i in items)
        assert all(i["sampleNature"] == "synthetic" for i in items)
        limited = {**env["policy"], "maxOperatorSteps": 1}
        assert not any(
            i["available"] for i in list_demos(env["owner"], limited)["items"]
        )
        AgentRuntime.objects.filter(name="workflow-worker").delete()
        assert not any(
            i["available"] for i in list_demos(env["owner"], env["policy"])["items"]
        )
        assert not list_demos(env["outsider"], env["policy"])["items"]
        ProjectMembership.objects.filter(
            project=env["project"], user=env["owner"]
        ).delete()
        assert not list_demos(env["owner"], env["policy"])["items"]


def test_directory_shows_unready_entry_without_input_names(demo):  # noqa: F811
    env = demo
    with project_scope(
        ProjectScope((env["project"].id,), env["project"].id, env["owner"].id)
    ):
        mark(env)
    with project_scope(ProjectScope((1,), 1, env["owner"].id)):
        result = list_demos(env["owner"], env["policy"])
    assert result["items"] and not any(i["available"] for i in result["items"])
    assert all(
        set(i)
        == {
            "scenario",
            "projectId",
            "projectName",
            "title",
            "prompt",
            "sampleNature",
            "available",
        }
        for i in result["items"]
    )


def test_current_project_returns_live_preset_without_cross_project_inputs(demo):  # noqa: F811
    env = demo
    scope = ProjectScope((env["project"].id,), env["project"].id, env["owner"].id)
    with project_scope(scope):
        mark(env)
        item = next(
            value
            for value in list_demos(env["owner"], env["policy"])["items"]
            if value["scenario"] == "ecology_investigation"
        )
        assert item["preset"]["inputs"] == {
            role: env["inputs"][role]
            for role in ("early_image", "late_image", "valid_mask", "zones", "context")
        }
        assert item["preset"]["parameters"]["red"] == 1
        assert item["preset"]["parameters"]["early_date"] == "2025-09-15"
    # The same authorized project can be advertised elsewhere, without inputs.
    with project_scope(ProjectScope((1,), 1, env["owner"].id)):
        other = list_demos(env["owner"], env["policy"])["items"]
        assert other and all("preset" not in value for value in other)


def test_preset_tracks_activity_and_visibility_instead_of_old_names(demo):  # noqa: F811
    env = demo
    with project_scope(
        ProjectScope((env["project"].id,), env["project"].id, env["owner"].id)
    ):
        mark(env)
        previous = DataResource.objects.get(pk=env["inputs"]["early_image"])
        previous.source = "retired-original-version"
        previous.save()
        current = DataResource.objects.create(
            code="new-image",
            name="重新命名的前期影像",
            source=MARKERS["early_image"][1],
            data_type="raster",
            maintainer=env["owner"],
        )

        def preset():
            return next(
                value["preset"]
                for value in list_demos(env["owner"], env["policy"])["items"]
                if value["scenario"] == "ecology_investigation"
            )

        assert preset()["inputs"]["early_image"] == current.id
        current.owner_only, current.maintainer = True, env["outsider"]
        current.save()
        assert "early_image" not in preset()["inputs"]
        assert previous.id not in preset()["inputs"].values()
