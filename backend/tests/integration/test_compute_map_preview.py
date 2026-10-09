import io

import numpy as np
from PIL import Image
import pytest
import rasterio
from rasterio.transform import from_bounds

from apps.catalog.models import DataResource
from apps.compute.models import ComputeImport, ComputeOutput
from apps.compute.packages import checksum
from apps.compute.serializers import output_data
from apps.compute.worker import task_scope
from apps.core.storage import app_path
from apps.projects.models import ProjectMembership
from . import test_compute as shared
from .test_compute_recovery import make_output

setup_compute = shared.setup_compute
pytestmark = pytest.mark.django_db


@pytest.fixture
def map_result(setup_compute):
    env = setup_compute
    task, path = make_output(env, "raster", "index.tif")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=32,
        height=24,
        count=1,
        dtype="float32",
        crs="EPSG:32645",
        nodata=-9999,
        transform=from_bounds(615864, 4444548, 615992, 4444676, 32, 24),
    ) as dst:
        values = np.full((24, 32), 0.5, dtype="float32")
        values[0, 0] = -9999
        dst.write(values, 1)
    output = ComputeOutput.objects.create(
        task=task,
        key="ndvi",
        label="NDVI",
        kind="raster",
        file_name=path.name,
        path=path.relative_to(app_path()).as_posix(),
        size_bytes=path.stat().st_size,
        checksum=checksum(path),
        metadata={"bands": 1, "crs": "EPSG:32645"},
    )
    return env, task, output, path


def url(env, output, image=False):
    suffix = "image/" if image else ""
    return f"/api/compute/outputs/{output.id}/map-preview/{suffix}?projectTagId={env['project'].id}"


def test_map_preview_is_real_png_without_registration(map_result):
    env, task, output, path = map_result
    resources = DataResource.objects.count()
    source = path.read_bytes()
    response = env["client"].get(url(env, output))
    assert response.status_code == 200, response.content
    preview = response.json()
    assert preview["temporary"] is True and preview["kind"] == "raster"
    assert len(preview["imageCoordinates"]) == 4
    assert preview["name"] == task.name + " \u00b7 NDVI"
    image = env["client"].get(preview["imageUrl"])
    assert image.status_code == 200 and image["Content-Type"] == "image/png"
    with Image.open(io.BytesIO(image.content)) as png:
        assert png.mode == "RGBA" and png.width <= 1024
    assert "no-store" in image["Cache-Control"]
    assert DataResource.objects.count() == resources
    assert ComputeImport.objects.count() == 0
    assert path.read_bytes() == source


def test_map_preview_rechecks_owner_project_and_revoked_inputs(map_result):
    env, _, output, _ = map_result
    client = env["client"]
    # A query/header conflict cannot silently change project scope.
    assert client.get(url(env, output), HTTP_X_PROJECT_ID="1").status_code == 400
    assert (
        client.get(
            f"/api/compute/outputs/{output.id}/map-preview/?projectTagId=1"
        ).status_code
        == 404
    )
    ProjectMembership.objects.create(project=env["project"], user=env["outsider"])
    client.force_login(env["outsider"])
    assert client.get(url(env, output)).status_code == 404
    client.force_login(env["owner"])
    resource = env["resource"]
    resource.owner_only = True
    resource.maintainer = env["outsider"]
    resource.save(update_fields=["owner_only", "maintainer"])
    assert client.get(url(env, output)).status_code == 403
    assert client.get(url(env, output, True)).status_code == 403


def test_expiration_and_file_tampering_do_not_return_cached_image(map_result):
    env, _, output, path = map_result
    assert env["client"].get(url(env, output)).status_code == 200
    path.write_bytes(path.read_bytes() + b"tampered")
    assert env["client"].get(url(env, output, True)).status_code == 409
    output.expired = True
    output.save(update_fields=["expired"])
    assert env["client"].get(url(env, output)).status_code == 404


def test_registered_location_is_authorized_and_friendly(map_result):
    env, task, output, _ = map_result
    with task_scope(task):
        resource = DataResource.objects.create(
            name="NDVI result",
            code="index-result",
            data_type="raster",
            file_format="COG",
            storage_path="unused.tif",
            maintainer=env["owner"],
        )
        ComputeImport.objects.create(
            output=output,
            name=resource.name,
            requested_by=env["owner"],
            status="ready",
            resource=resource,
        )
        value = output_data(output)
        assert value["resourceName"] == resource.name
        assert (
            value["resourceLocation"]
            == env["project"].name + " / \u6570\u636e\u8d44\u6e90 / " + resource.name
        )
        assert f"resourceId={resource.id}" in value["mapUrl"]
        resource.maintainer = env["outsider"]
        resource.owner_only = True
        resource.save(update_fields=["maintainer", "owner_only"])
        hidden = output_data(output)
        assert (
            hidden["resourceName"]
            == hidden["resourceLocation"]
            == hidden["mapUrl"]
            == ""
        )
