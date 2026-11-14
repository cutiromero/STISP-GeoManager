"""Only real owner imports become products; reads use bounded metadata."""

from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied

from apps.catalog.models import DataResource
from apps.compute.models import ComputeTask, ComputeInput, ComputeOutput, ComputeImport
from apps.ecology.landcover import CODES, register_import
from apps.ecology.models import RemoteSensingProduct
from apps.ecology.monitoring import monitoring_snapshot
from apps.projects.context import ProjectScope, project_scope
from apps.projects.features import set_feature
from apps.projects.models import ProjectFeature
from tests.integration.test_compute import setup_compute  # noqa: F401

# ruff: noqa: F811


@pytest.fixture
def imported(setup_compute):
    env = setup_compute
    version = env["version"]
    version.algorithm.identifier = "landcover-unet-infer"
    version.algorithm.save(update_fields=["identifier"])
    env["scope"] = ProjectScope(
        (env["project"].pk,), env["project"].pk, env["owner"].pk
    )
    with project_scope(env["scope"]):
        feature, _ = ProjectFeature.objects.get_or_create(key="ecology_monitor")
        set_feature(
            env["admin"],
            feature,
            project=env["project"],
            enabled=True,
            config={
                "title": "地表覆盖",
                "source": "remote_sensing_products",
                "scenes": ["landcover"],
                "initialView": {"center": [107, 36], "zoom": 0.3, "regionZoom": 10},
            },
        )
        source = DataResource.objects.create(
            name="原始RGB",
            code="landcover-source",
            data_type="raster",
            coordinate_system="EPSG:3857",
            storage_path="source.tif",
            source="landcover-handoff:test",
        )
        task = ComputeTask.objects.create(
            owner=env["owner"],
            version=version,
            status="succeeded",
            idempotency_key=uuid4().hex,
            request_hash="a" * 64,
        )
        ComputeInput.objects.create(task=task, key="image", resource=source)
        colors = {
            1: "#FFD266",
            2: "#FFFD5B",
            4: "#27C223",
            5: "#79DAFF",
            6: "#FFB9B9",
            8: "#F31717",
        }
        facts = {
            "mode": "complete",
            "validAreaKm2": 0.000024,
            "priority": ["建筑", "水体", "耕地", "林地", "道路"],
            "statistics": [
                {
                    "code": code,
                    "name": name,
                    "color": colors[code],
                    "pixelCount": 1,
                    "areaKm2": 0.000004,
                    "percent": 100 / 6,
                }
                for code, name in CODES.items()
            ],
            "models": [
                {"class": name, "modelSha256": "b" * 64}
                for name in ["building", "water", "farmland", "forest", "road"]
            ],
        }
        output = ComputeOutput.objects.create(
            task=task,
            key="classification",
            kind="raster",
            file_name="result.tif",
            path="unused.tif",
            size_bytes=1,
            checksum="c" * 64,
            metadata={
                "rasterKind": "categorical",
                "qualityCheck": {
                    "version": 1,
                    "status": "passed",
                    "summary": "网格与分类通过",
                    "metrics": {},
                },
                "knowledgeFacts": {"landcover": facts},
            },
        )
        result = DataResource.objects.create(
            name="分类成果",
            code="landcover-result",
            data_type="raster",
            coordinate_system="EPSG:3857",
            storage_path="result.tif",
            is_compute_result=True,
        )
        record = ComputeImport.objects.create(
            output=output,
            requested_by=env["owner"],
            resource=result,
            name="分类成果",
            status="ready",
            storage_key=uuid4().hex,
        )
    return env, task, source, record


def test_owner_import_is_idempotent_and_snapshot_never_reads_pixels(
    imported, monkeypatch
):
    import rasterio

    env, _, source, record = imported
    monkeypatch.setattr(
        rasterio, "open", lambda *a, **kw: pytest.fail("产品元信息不应读取科学像元")
    )
    with project_scope(env["scope"]):
        product, created = register_import(record.pk)
        assert created
        assert not register_import(record.pk)[1]
        snapshot = monitoring_snapshot(env["owner"], "landcover")
        assert snapshot["items"][0]["resourceId"] == record.resource_id
        assert snapshot["items"][0]["classification"]["mode"] == "complete"
        assert [row["id"] for row in snapshot["inputResources"]] == [source.pk]
        source.status = "archived"
        source.save(update_fields=["status"])
        assert monitoring_snapshot(env["owner"], "landcover")["items"] == []
        assert RemoteSensingProduct.objects.filter(pk=product.pk).exists()


def test_trials_and_foreign_project_sources_do_not_publish(imported):
    env, task, _, record = imported
    with project_scope(env["scope"]):
        task.trial = True
        task.save(update_fields=["trial"])
        assert register_import(record.pk) is None
        task.trial = False
        task.save(update_fields=["trial"])
    from apps.projects.context import ProjectScope

    with project_scope(
        ProjectScope(
            (env["other_project"].pk,), env["other_project"].pk, env["admin"].pk, True
        )
    ):
        foreign = DataResource.objects.create(
            name="另一项目RGB",
            code="foreign",
            data_type="raster",
            storage_path="foreign.tif",
        )
    ComputeInput.objects.create(task=task, key="foreign", resource=foreign)
    with project_scope(env["scope"]), pytest.raises(PermissionDenied):
        register_import(record.pk)
    assert RemoteSensingProduct.objects.count() == 0


def test_stage_cache_retention_protects_active_retry(imported):
    import os
    import time
    from apps.compute.gpu_runtime import clean_stage_caches
    from apps.core.storage import app_path

    env, task, _, _ = imported
    with project_scope(env["scope"]):
        old = app_path(
            "projects",
            str(task.project_tag_id),
            "cache",
            "landcover",
            str(task.owner_id),
            str(task.pk),
        )
        old.mkdir(parents=True)
        (old / "mask.tif").write_bytes(b"scratch")
        timestamp = time.time() - 172800
        os.utime(old, (timestamp, timestamp))
        retry = ComputeTask.objects.create(
            owner=env["owner"],
            version=task.version,
            status="queued",
            retry_of=task,
            idempotency_key=uuid4().hex,
            request_hash="d" * 64,
        )
        clean_stage_caches(time.time() - 86400)
        assert old.is_dir()
        retry.status = "failed"
        retry.save(update_fields=["status"])
        clean_stage_caches(time.time() - 86400)
        assert not old.exists()
