"""Source previews preserve raw arrays, share bounded work and recheck live ACLs."""

from pathlib import Path
from unittest.mock import patch
import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from apps.catalog.models import DataResource
from apps.catalog.monitoring_metadata import update_metadata
from apps.core.storage import raster_source_path
from apps.projects.context import ProjectScope, project_scope
from apps.ecology.source_preview import request_preview, readable_job, _FLIGHTS
from tests.integration.test_compute import setup_compute  # noqa:F401
from tests.integration.test_native_cube_inputs import write_cube
from tests.integration.test_wildfire_observation import enable

# ruff:noqa:F811
pytestmark = pytest.mark.django_db


def test_real_native_preview_has_atomic_png_and_dedup_and_rejects_revocation(
    setup_compute,
):
    env = setup_compute
    with project_scope(
        ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    ):
        enable(env)
        from django.contrib.auth.models import Permission

        env["owner"].user_permissions.add(
            Permission.objects.get(codename="load_raster_layer")
        )
        root = raster_source_path("preview-real.zarr")
        write_cube(root)
        before = {
            str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }
        resource = DataResource.objects.create(
            code="preview-cube",
            name="原始立方体",
            data_type="raster",
            file_format="ZARR",
            storage_path="original/uploaded/preview-real.zarr",
            maintainer=env["owner"],
        )
        # raster_source_path adds the configured original/uploaded root.
        from apps.compute.cube_inputs import cube_root

        resource.storage_path = str(root.relative_to(root.parents[1]))
        resource.save()
        assert cube_root(resource) == root
        update_metadata(
            env["admin"],
            resource,
            {"usages": [{"scene": "wildfire", "purpose": "input"}]},
        )
        _FLIGHTS.clear()
        submitted = []
        with patch(
            "apps.raster.services.jobs._submit_job",
            side_effect=lambda job, runner: submitted.append(runner),
        ):
            first = request_preview(env["owner"], "wildfire", resource.pk, "gwis_ba", 2)
            second = request_preview(
                env["owner"], "wildfire", resource.pk, "gwis_ba", 2
            )
        assert first.id == second.id and len(submitted) == 1
        assert first.status == "queued"
        submitted[0]()
        job = readable_job(env["owner"], first.id)
        assert job.status == "ready", job.error
        assert Path(job.artifact_path).read_bytes().startswith(b"\x89PNG")
        assert job.result["ordinal"] == 2 and job.result["bounds"] == [
            -180,
            -85,
            180,
            85,
        ]
        assert before == {
            str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }
        _FLIGHTS.clear()
        with (
            patch("apps.raster.services.jobs._submit_job") as submit,
            patch("apps.compute.native_cube_reader.Cube.observation") as pixels,
        ):
            cached = request_preview(
                env["owner"], "wildfire", resource.pk, "gwis_ba", 2
            )
            assert cached.status == "ready"
            submit.assert_not_called()
            pixels.assert_not_called()
        resource.status = "inactive"
        resource.save()
        with pytest.raises(PermissionDenied):
            readable_job(env["owner"], first.id)
        with pytest.raises(PermissionDenied):
            request_preview(env["owner"], "wildfire", resource.pk, "gwis_ba", 2)


def test_invalid_period_never_schedules_pixel_work(setup_compute):
    env = setup_compute
    with project_scope(
        ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    ):
        enable(env)
        from django.contrib.auth.models import Permission

        env["owner"].user_permissions.add(
            Permission.objects.get(codename="load_raster_layer")
        )
        root = raster_source_path("preview-invalid.zarr")
        write_cube(root)
        resource = DataResource.objects.create(
            code="preview-invalid",
            name="立方体",
            data_type="raster",
            file_format="ZARR",
            storage_path=str(root.relative_to(root.parents[1])),
            maintainer=env["owner"],
        )
        update_metadata(
            env["admin"],
            resource,
            {"usages": [{"scene": "wildfire", "purpose": "input"}]},
        )
        with patch("apps.raster.services.jobs._submit_job") as submit:
            for product, ordinal in [("gwis_ba", 1), ("bad", 2), ("gwis_ba", 2000)]:
                with pytest.raises(ValidationError):
                    request_preview(
                        env["owner"], "wildfire", resource.pk, product, ordinal
                    )
            submit.assert_not_called()
