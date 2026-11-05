"""Independent acceptance maps never become real correction scenario inputs."""

import hashlib
from types import SimpleNamespace

import pytest
from django.core.exceptions import PermissionDenied
from django.core.management.base import CommandError

from apps.agent.demo_workflow import prepare_demo
from apps.agent.geology_reference import MATERIAL_SOURCE_PREFIX, REFERENCE_SOURCE_PREFIX
from apps.agent.management.commands.prepare_real_geology_case import import_resource
from apps.agent.research_presets import AGE_MARKERS, discover
from apps.catalog.models import DataResource
from apps.compute.models import ComputeTask
from apps.projects.context import ProjectScope, project_scope
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo, scenario  # noqa: F401

pytestmark = pytest.mark.django_db


def age_scene(result):
    return next(
        scene
        for scene in result["scenarios"]
        if scene["scenario"] == "geology_age_correction"
    )


@pytest.mark.parametrize("reference", [False, True])
def test_import_reference_marker_is_explicit_and_idempotent(setup_compute, reference):  # noqa: F811
    env = setup_compute
    path = env["tmp"] / "material.csv"
    path.write_text("feature_id,description\na,独立资料\n", encoding="utf-8")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    item = {
        "file": path.name,
        "sha256": sha,
        "referenceOnly": reference,
        "code": "new-case-material",
        "name": "独立对照" if reference else "真实算法输入",
        "kind": "table",
        "description": "用途已注明",
    }
    with project_scope(
        ProjectScope((env["project"].id,), env["project"].id, env["owner"].id)
    ):
        before = DataResource.objects.count()
        resource = import_resource(env["owner"], env["tmp"], item)
        assert (
            resource.source
            == (REFERENCE_SOURCE_PREFIX if reference else MATERIAL_SOURCE_PREFIX) + sha
        )
        assert import_resource(env["owner"], env["tmp"], item).id == resource.id
        assert DataResource.objects.count() == before + 1
        with pytest.raises(CommandError, match="已变更"):
            import_resource(
                env["owner"], env["tmp"], {**item, "referenceOnly": not reference}
            )


def test_invalid_reference_flag_rejected_before_resource_writes(setup_compute):  # noqa: F811
    env = setup_compute
    path = env["tmp"] / "material.csv"
    path.write_text("x\n1\n", encoding="utf-8")
    item = {
        "file": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "referenceOnly": "false",
        "code": "invalid-reference",
        "name": "非法标记",
        "kind": "table",
        "description": "",
    }
    with project_scope(
        ProjectScope((env["project"].id,), env["project"].id, env["owner"].id)
    ):
        before = DataResource.objects.count()
        with pytest.raises(CommandError, match="布尔"):
            import_resource(env["owner"], env["tmp"], item)
        assert DataResource.objects.count() == before


@pytest.mark.parametrize("manual", [False, True])
@pytest.mark.parametrize("reference_role", ["initial_map", "surveys", "rules"])
def test_discovery_filters_reference_even_when_manually_selected(
    demo,  # noqa: F811
    manual,
    reference_role,  # noqa: F811
):  # noqa: F811
    env = demo
    with project_scope(
        ProjectScope((env["project"].id,), env["project"].id, env["owner"].id)
    ):
        selected, expected = [], {}
        for role, (_, marker) in AGE_MARKERS.items():
            kind = "vector" if role == "initial_map" else "table"
            resource = DataResource.objects.create(
                name=role,
                code=marker,
                data_type=kind,
                source=(
                    REFERENCE_SOURCE_PREFIX
                    if role == reference_role
                    else MATERIAL_SOURCE_PREFIX
                )
                + "a" * 64,
                maintainer=env["owner"],
            )
            selected.append(resource.id)
            expected[role] = resource.id
        run = SimpleNamespace(
            resource_ids=selected,
            data_selection_mode="manual" if manual else "auto",
            algorithm_version_ids=[],
            algorithm_selection_mode="auto",
        )
        scene = age_scene(discover(env["owner"], env["policy"], run))
        excluded_id = expected[reference_role]
        assert all(
            excluded_id != row["id"]
            for rows in scene["inputs"].values()
            for row in rows
        )
        for role in set(AGE_MARKERS) - {reference_role}:
            assert expected[role] in [row["id"] for row in scene["inputs"][role]]
        assert expected[reference_role] not in scene["preferredInputs"].values()


@pytest.mark.parametrize("reference_role", ["initial_map", "surveys", "rules"])
def test_prepare_rejects_direct_reference_binding_before_checkpoint_or_task(
    demo,  # noqa: F811
    reference_role,  # noqa: F811
):  # noqa: F811
    env = demo
    with project_scope(
        ProjectScope((env["project"].id,), env["project"].id, env["owner"].id)
    ):
        original = DataResource.objects.get(pk=env["inputs"][reference_role])
        reference = DataResource.objects.create(
            name="独立验收参考",
            code="reference-only-material",
            data_type=original.data_type,
            source=REFERENCE_SOURCE_PREFIX + "b" * 64,
            maintainer=env["owner"],
        )
        env["inputs"][reference_role] = reference.id
        workflow = scenario(env, "geology_age_correction")
        original_plan = workflow.plan.copy()
        before = ComputeTask.objects.count()
        with pytest.raises(PermissionDenied, match="未绑定到当前科研任务"):
            prepare_demo(workflow, env["owner"], env["policy"])
        workflow.refresh_from_db()
        assert workflow.plan == original_plan
        assert not workflow.checkpoints.exists()
        assert ComputeTask.objects.count() == before
