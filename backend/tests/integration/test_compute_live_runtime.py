"""Opt-in acceptance against a real Linux container; never run uploaded code locally.

Run after installing the runtime with GEOMANAGER_COMPUTE_LIVE=1. All business
records and scientific fixtures are in pytest's isolated database/data roots.
"""

import json
import os
import sqlite3
import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.catalog.models import DataResource
from apps.compute.models import AlgorithmVersion, ComputeImport, ComputeTask
from apps.compute.packages import ComputeError
from apps.compute.runtime import command, execute, inspect_runtime
from apps.compute.templates import build_package
from apps.compute.worker import process_import, pulse, run_task, task_scope
from apps.core.storage import app_path, raster_source_path, table_data_path
from apps.core.storage import vector_geopackage_path
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import Project, ProjectMembership
from apps.raster.models import RasterDataset

pytestmark = pytest.mark.skipif(
    os.environ.get("GEOMANAGER_COMPUTE_LIVE") != "1",
    reason="Requires explicitly enabled real Linux container acceptance",
)


def request(client, path, project=1, body=None):
    kwargs = {"HTTP_X_PROJECT_ID": str(project)}
    if body is None:
        result = client.get("/api/compute/" + path, **kwargs)
    else:
        result = client.post(
            "/api/compute/" + path,
            data=json.dumps(body),
            content_type="application/json",
            **kwargs,
        )
    assert result.status_code == 200, result.content
    return result


def sample_resources(project, actor):
    import geopandas as gpd
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from shapely.geometry import Point

    with project_scope(ProjectScope((project,), project, actor.id)):
        table = table_data_path("data.sqlite")
        table.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(table) as db:
            db.execute("CREATE TABLE samples (region TEXT, value REAL)")
            db.executemany(
                "INSERT INTO samples VALUES (?, ?)", [("A", 1), ("A", 3), ("B", 7)]
            )
        tabular = DataResource.objects.create(
            name="人工构造验收表格",
            code="live-table",
            data_type="table",
            storage_path="samples",
            file_format="SQLITE",
            item_count=3,
        )
        gpkg = vector_geopackage_path()
        gpkg.parent.mkdir(parents=True, exist_ok=True)
        gpd.GeoDataFrame(
            {"name": ["验收点"]}, geometry=[Point(80, 40)], crs=4326
        ).to_file(gpkg, layer="samples", driver="GPKG")
        vector = DataResource.objects.create(
            name="人工构造验收点",
            code="live-vector",
            data_type="vector",
            storage_path="samples",
            file_format="GPKG",
            coordinate_system="EPSG:4326",
        )
        raster = raster_source_path("live-example.tif")
        raster.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(
            raster,
            "w",
            driver="GTiff",
            width=3,
            height=2,
            count=2,
            dtype="float32",
            nodata=-9999,
            crs="EPSG:4326",
            transform=from_origin(80, 40, 0.01, 0.01),
        ) as dst:
            dst.write(
                np.array(
                    [
                        [[1, 2, 0], [3, -9999, 10]],
                        [[3, 6, 0], [9, 5, 10]],
                    ],
                    dtype="float32",
                )
            )
        image = DataResource.objects.create(
            name="人工构造验收栅格",
            code="live-raster",
            data_type="raster",
            storage_path="live-example.tif",
            file_format="GTIFF",
            coordinate_system="EPSG:4326",
        )
        RasterDataset.objects.create(
            name=image.name,
            code=image.code,
            data_resource=image,
            source_relative_path="live-example.tif",
            status="ready",
            band_count=2,
        )
        return {"table": tabular.id, "vector": vector.id, "raster": image.id}


@pytest.fixture
def live(settings, tmp_path):
    settings.PROJECT_CONFIG = replace(
        settings.PROJECT_CONFIG,
        app_data=tmp_path / "app",
        research_data_root=tmp_path / "research",
    )
    state = inspect_runtime()
    assert state["ready"], state
    admin = get_user_model().objects.create_superuser("live_admin", password="test")
    user = get_user_model().objects.create_user("live_researcher", password="test")
    user.user_permissions.add(
        *Permission.objects.filter(
            codename__in=[
                "submit_task",
                "view_own_task",
                "cancel_own_task",
                "browse_data",
                "add_dataresource",
                "export_dataresource",
            ]
        )
    )
    private = Project.objects.create(name="隔离验收项目", code="live-acceptance")
    ProjectMembership.objects.create(project=private, user=user)
    admin_client, client = Client(), Client()
    admin_client.force_login(admin)
    client.force_login(user)
    return SimpleNamespace(
        admin=admin,
        user=user,
        admin_client=admin_client,
        client=client,
        private=private.id,
        public_inputs=sample_resources(1, admin),
        private_inputs=sample_resources(private.id, user),
        state=state,
        tmp=tmp_path,
    )


CASES = [
    (1, "raster", "source", {"band": 1, "scale": 2, "offset": 3}),
    (2, "vector", "features", {"distance": 100}),
    (3, "table", "table", {"group": "region", "value": "value", "method": "mean"}),
    (4, "raster", "image", {"red": 1, "nir": 2}),
]


def verify_numbers(output, template):
    import geopandas as gpd
    import numpy as np
    import pandas as pd
    import rasterio

    path = app_path(output.path)
    if template in (1, 4):
        with rasterio.open(path) as src:
            assert src.crs.to_epsg() == 4326 and src.count == 1
            expected = (
                [[5, 7, 3], [9, -9999, 23]]
                if template == 1
                else [[0.5, 0.5, -9999], [0.5, -9999, 0]]
            )
            np.testing.assert_allclose(src.read(1), expected, atol=1e-6)
    elif template == 2:
        frame = gpd.read_file(path)
        assert len(frame) == 1 and frame.crs.to_epsg() == 4326
        assert 30000 < frame.to_crs(frame.estimate_utm_crs()).area.iloc[0] < 32000
    else:
        frame = pd.read_csv(path)
        assert frame["region"].tolist() == ["A", "B"]
        assert frame["value"].tolist() == [2, 7]


@pytest.mark.parametrize("template,kind,key,parameters", CASES)
def test_real_trial_publish_private_download_and_import(
    live, template, kind, key, parameters
):
    package, identifier = build_package(template)
    algorithm = request(
        live.admin_client,
        "algorithms/",
        body={
            "identifier": identifier,
            "name": "隔离验收算法",
            "enabled": True,
        },
    ).json()
    uploaded = live.admin_client.post(
        f"/api/compute/algorithms/{algorithm['id']}/versions/",
        {"file": SimpleUploadedFile("operator.zip", package)},
        HTTP_X_PROJECT_ID="1",
    )
    assert uploaded.status_code == 200, uploaded.content
    version = uploaded.json()["id"]
    for project, client, inputs, trial in [
        (1, live.admin_client, live.public_inputs, True),
        (live.private, live.client, live.private_inputs, False),
    ]:
        pulse(live.state)
        body = {
            "name": "真实容器验收",
            "versionId": version,
            "inputs": {key: inputs[kind]},
            "parameters": parameters,
            "trial": trial,
            "idempotencyKey": uuid.uuid4().hex,
        }
        row = request(client, "tasks/", project, body).json()
        task = ComputeTask._base_manager.get(pk=row["id"])
        with task_scope(task):
            run_task(task)
            task.refresh_from_db()
            assert task.status == "succeeded", task.error
            output = task.outputs.get()
            verify_numbers(output, template)
        assert command(
            "inspect", task.attempts.get().container_name, check=False
        ).returncode
        download = request(client, f"outputs/{output.id}/file/", project)
        assert (
            b"".join(download.streaming_content) == app_path(output.path).read_bytes()
        )
        request(client, f"outputs/{output.id}/preview/", project)
        if trial:
            request(
                live.admin_client, f"versions/{version}/", body={"action": "publish"}
            )
            assert AlgorithmVersion.objects.get(pk=version).status == "published"
        else:
            request(client, f"outputs/{output.id}/import/", project, {})
            request(client, f"outputs/{output.id}/import/", project, {})
            record = ComputeImport.objects.get(output=output)
            with task_scope(task):
                process_import(record)
            record.refresh_from_db()
            assert record.status == "ready", record.error
            assert record.resource.project_tag_id == project
            assert record.resource.status == "active"
            assert (
                client.get(
                    f"/api/compute/outputs/{output.id}/file/", HTTP_X_PROJECT_ID="1"
                ).status_code
                == 404
            )


def test_real_container_restrictions_and_cleanup(live):
    root = live.tmp / "container-probe"
    package, inputs, outputs = [
        root / name for name in ("algorithm", "inputs", "results")
    ]
    for path in (package, inputs, outputs):
        path.mkdir(parents=True)
    (inputs / "context.json").write_text('{"inputs":{},"parameters":{}}')
    (package / "main.py").write_text(
        "import os,socket\n"
        "def run(context):\n"
        " assert os.getuid()==10001\n"
        " assert not os.path.exists('/var/run/docker.sock')\n"
        " assert sorted(os.listdir('/sys/class/net'))==['lo']\n"
        " for p in ['/forbidden','/algorithm/forbidden','/inputs/forbidden']:\n"
        "  try: open(p,'w').close()\n"
        "  except OSError: pass\n"
        "  else: raise AssertionError(p)\n"
        " open(context.output_path('probe.csv'),'w').write('ok\\n1\\n')\n"
    )
    attempt = SimpleNamespace(
        container_name="gm-compute-" + uuid.uuid4().hex,
        runtime_digest=live.state["imageDigest"],
    )
    inspected = []

    def heartbeat():
        if not inspected:
            state = command("inspect", attempt.container_name, check=False)
            if state.returncode == 0:
                cfg = json.loads(state.stdout)[0]["HostConfig"]
                assert cfg["ReadonlyRootfs"] and cfg["NetworkMode"] == "none"
                assert "ALL" in cfg["CapDrop"] and cfg["PidsLimit"] == 64
                assert cfg["Memory"] > 0 and cfg["NanoCpus"] > 0
                assert "size=" in cfg["Tmpfs"]["/output"]
                inspected.append(True)

    execute(
        attempt,
        package,
        inputs,
        outputs,
        {"timeoutSeconds": 30, "outputs": [{"file": "probe.csv"}]},
        heartbeat,
    )
    assert inspected and (outputs / "probe.csv").read_text() == "ok\n1\n"
    assert command("inspect", attempt.container_name, check=False).returncode
    # Cancellation raised by the worker heartbeat must still remove the container.
    (package / "main.py").write_text("import time\ndef run(context): time.sleep(60)\n")
    attempt.container_name = "gm-compute-" + uuid.uuid4().hex

    def cancelled():
        raise ComputeError("acceptance cancellation")

    with pytest.raises(ComputeError, match="acceptance cancellation"):
        execute(
            attempt,
            package,
            inputs,
            outputs,
            {"timeoutSeconds": 30, "outputs": [{"file": "probe.csv"}]},
            cancelled,
        )
    assert command("inspect", attempt.container_name, check=False).returncode
