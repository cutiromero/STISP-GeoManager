"""Stage bounded originals and verify real, browser-started candidate workflows."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import time
import tomllib
from types import SimpleNamespace

# CONFIGURATION
ACTOR = "gongxt"
MAINTAINER = "admin"
WAIT_SECONDS = 1470
MAX_FILE_BYTES = 100_000_000
MAX_CUBE_BYTES = 280_000_000
WILDFIRE_TIME_INDEX = 873
WILDFIRE_YEAR = 2019
WILDFIRE_DATE = "2019-12-27"
LANDCOVER_SIZE = 1024
COASTAL_SIZE = 64
COASTAL_POINT = (121.92, 31.24)
PRODUCTION_CONFIG = Path("/root/autodl-tmp/geomanager-config-0.1.6-production/app.toml")
LAND_PATH = (
    "projects/2/raster/original/imported/landcover-handoff-20261114/region_01.tif"
)
COASTAL_PATH = "projects/13/raster/original/imported/spartina-handoff-20261114"
CUBE_PATH = (
    "projects/13/raster/original/imported/wildfire-handoff-20261114/seasfire_v0.4.zarr"
)
CODES = ("huanjiang-landcover", "spartina-distribution", "wildfire-history-observation")
CONTEXT_PATH = Path(__file__).with_name("candidate-context.json")


def private_json(path, value):
    with path.open("x") as stream:
        path.chmod(0o600)
        json.dump(value, stream, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, default=CONTEXT_PATH)
    context = json.loads(parser.parse_args().context.read_text())
    root, code, config = (
        Path(context[key]).resolve() for key in ("root", "code", "config")
    )
    assert code.is_relative_to(root) and config.is_relative_to(root)
    os.chdir(code / "backend")
    sys.path.insert(0, str(code / "backend"))
    os.environ["DJANGO_SETTINGS_MODULE"] = "geomanager.settings"
    import django

    django.setup()
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.test import Client
    from osgeo import gdal
    import rasterio
    from rasterio.windows import Window
    from apps.agent.models import AgentWorkflow, AgentWorkflowStep
    from apps.business_flows.models import BusinessFlowDefinition
    from apps.business_flows.execution_session import session as workflow_session
    from apps.catalog.models import DataResource
    from apps.catalog.monitoring_metadata import update_metadata
    from apps.compute.cube_inputs import source_dependencies
    from apps.compute.models import AlgorithmVersion, ComputeImport
    from apps.compute.native_cube_reader import Cube
    from apps.core.browser_sessions import prepare_browser_session
    from apps.core.storage import app_path, raster_source_path
    from apps.ecology.models import RemoteSensingProduct
    from apps.projects.access import can_access_project
    from apps.projects.context import ProjectScope, project_scope
    from apps.raster.services.importer import import_raster_file

    assert Path(settings.DATABASES["default"]["NAME"]).resolve().is_relative_to(root)
    storage = tomllib.loads(PRODUCTION_CONFIG.read_text())["application"]["storage"]
    original_research = Path(storage["research_data_root"]).resolve()
    original_app = Path(storage["app_data"]).resolve()
    actor = get_user_model().objects.get(username=ACTOR, is_active=True)
    call_command("publish_monitoring_workflows", actor=MAINTAINER, apply=True)
    flows = {
        flow.code: flow
        for flow in BusinessFlowDefinition._base_manager.filter(
            code__in=CODES,
            is_active=True,
        ).select_related("current_version", "project_tag")
    }
    assert flows.keys() == set(CODES)
    gdal.UseExceptions()
    cases = {}
    for index, code_name in enumerate(CODES):
        flow = flows[code_name]
        assert can_access_project(actor, flow.project_tag_id)
        scope = ProjectScope((flow.project_tag_id,), flow.project_tag_id, actor.pk)
        version = flow.current_version
        assert version.definition.get("executionMode") == "main_agent"
        node = version.definition["nodes"][0]
        algorithm = AlgorithmVersion.objects.get(pk=node["algorithmVersionId"])
        # A previously validated immutable package is the only compute code staged.
        source = (original_app / algorithm.package_path).resolve(strict=True)
        target = app_path(algorithm.package_path).resolve()
        assert source.is_relative_to(original_app) and target.is_relative_to(root)
        assert source.stat().st_size < MAX_FILE_BYTES
        with source.open("rb") as stream:
            assert (
                hashlib.file_digest(stream, "sha256").hexdigest() == algorithm.checksum
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        with project_scope(scope):
            inputs = {}
            if index == 0:
                source = (original_research / LAND_PATH).resolve(strict=True)
                assert source.is_relative_to(original_research)
                path = root / "research" / "landcover-qa.tif"
                image = gdal.Translate(
                    str(path),
                    str(source),
                    srcWin=[0, 0, LANDCOVER_SIZE, LANDCOVER_SIZE],
                    creationOptions=["COMPRESS=DEFLATE", "TILED=YES"],
                )
                image.Close()
                raster = import_raster_file(
                    path,
                    name="候选验收 · 2米原始RGB",
                    uploader_id=actor.pk,
                    raster_kind="imagery",
                )
                inputs["image"] = raster.data_resource
            elif index == 1:
                for role, month in (
                    ("march", "03"),
                    ("august", "08"),
                    ("december", "12"),
                ):
                    path = root / "research" / f"spartina-qa-{month}.tif"
                    source = (
                        original_research / COASTAL_PATH / f"merged_sat_2025{month}.tif"
                    ).resolve(strict=True)
                    assert source.is_relative_to(original_research)
                    with rasterio.open(source) as image:
                        row, column = image.index(*COASTAL_POINT)
                        window = Window(column, row, COASTAL_SIZE, COASTAL_SIZE)
                        profile = {
                            **image.profile,
                            "width": COASTAL_SIZE,
                            "height": COASTAL_SIZE,
                            "transform": image.window_transform(window),
                            "tiled": True,
                            "blockxsize": 32,
                            "blockysize": 32,
                            "compress": "deflate",
                        }
                        with rasterio.open(path, "w", **profile) as narrowed:
                            narrowed.write(image.read(window=window))
                            for band, name in enumerate(image.descriptions, 1):
                                if name:
                                    narrowed.set_band_description(band, name)
                    raster = import_raster_file(
                        path,
                        name=f"候选验收 · 三时相2025-{month}",
                        uploader_id=actor.pk,
                        raster_kind="imagery",
                    )
                    resource = raster.data_resource
                    update_metadata(
                        actor,
                        resource,
                        {
                            "family": "raster",
                            "collectionKey": "candidate-spartina",
                            "precision": "day",
                            "startsAt": f"2025-{month}-01",
                            "endsAt": f"2025-{month}-01",
                            "usages": [{"scene": "spartina", "purpose": "input"}],
                        },
                        require_edit=False,
                    )
                    inputs[role] = resource
            else:
                source = (original_research / CUBE_PATH).resolve(strict=True)
                assert source.is_relative_to(original_research)
                original = Cube(source)
                plan = original.plan(
                    "gwis_ba", WILDFIRE_TIME_INDEX, [-180, -90, 180, 90], 1
                )
                dependencies = set(source_dependencies(source, plan)) | {
                    source / name for name in (".zmetadata", ".zgroup", ".zattrs")
                }
                for product in ("gfed_ba", "fcci_ba"):
                    # Indexing needs the small validity arrays, not the other data products.
                    path = source / f"{product}_valid_mask"
                    dependencies.update(path.iterdir())
                size = sum(path.stat().st_size for path in dependencies)
                assert size <= MAX_CUBE_BYTES and all(
                    path.is_file()
                    and not path.is_symlink()
                    and path.stat().st_size < MAX_FILE_BYTES
                    for path in dependencies
                ), "原生资料子集超过候选范围"
                cube_path = raster_source_path("candidate-monitoring.zarr")
                assert cube_path.resolve().is_relative_to(root)
                for path in dependencies:
                    target = cube_path / path.relative_to(source)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
                resource = DataResource.objects.create(
                    name="候选验收 · SeasFire原生Zarr",
                    code="wildfire-seasfire-cube-candidate-32",
                    data_type="raster",
                    file_format="ZARR",
                    storage_path="original/candidate-monitoring.zarr",
                    coordinate_system="EPSG:4326",
                    size_bytes=size,
                    item_count=len(original.dates),
                    maintainer=actor,
                )
                update_metadata(
                    actor,
                    resource,
                    {
                        "family": "seasfire",
                        "collectionKey": "candidate-wildfire",
                        "usages": [{"scene": "wildfire", "purpose": "input"}],
                    },
                    require_edit=False,
                )
                inputs["cube"] = resource
            cases[code_name] = {
                "project": flow.project_tag_id,
                "projectName": flow.project_tag.name,
                "versionId": version.pk,
                "flowId": flow.pk,
                "goal": f"3.2 候选浏览器验收 · {index + 1}",
                "inputs": {
                    label: {"id": value.pk, "name": value.name}
                    for label, value in inputs.items()
                },
                "year": WILDFIRE_YEAR,
                "date": WILDFIRE_DATE,
            }

    client = Client(HTTP_HOST="127.0.0.1")
    client.force_login(actor)
    session = client.session
    prepare_browser_session(SimpleNamespace(session=session))
    session.save()
    credentials = {
        "pageId": secrets.token_hex(16),
        "token": secrets.token_hex(32),
        "sequence": 1,
    }
    response = client.post(
        "/api/auth/browser-session/",
        {"action": "start", **credentials},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    assert client.get("/api/auth/csrf/").status_code == 200
    browser_session = {**credentials, "familyId": response.json()["familyId"]}
    private_json(
        root / "monitoring-browser-qa.json",
        {
            "ready": True,
            "actor": ACTOR,
            "userId": actor.pk,
            "baseUrl": context["baseUrl"],
            "cases": cases,
            "session": browser_session,
            "cookies": [
                {"name": key, "value": item.value}
                for key, item in client.cookies.items()
            ],
        },
    )

    checks = {}
    expires = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < expires:
        for code_name, case in cases.items():
            if checks.get(code_name):
                continue
            workflow = (
                AgentWorkflow._base_manager.filter(
                    owner=actor,
                    goal__startswith=case["goal"],
                    project_tag_id=case["project"],
                )
                .order_by("-created_at")
                .first()
            )
            if workflow is None:
                continue
            if workflow.status in {
                "failed",
                "cancelled",
                "interrupted",
                "waiting_approval",
            }:
                raise RuntimeError(f"{code_name}: {workflow.status} {workflow.detail}")
            if workflow.status != "succeeded":
                continue
            step = AgentWorkflowStep.objects.get(
                workflow=workflow, kind="submit_operator"
            )
            assert (
                workflow.model
                and workflow_session(workflow).get("id")
                and len(workflow.result_resource_ids) >= 2
            )
            assert not workflow_session(workflow)["loop"].get("activeNodeId")
            assert (
                ComputeImport.objects.filter(
                    output__task_id=step.compute_task_id, status="ready"
                ).count()
                >= 2
            )
            published = RemoteSensingProduct._base_manager.filter(
                data_resource_id__in=workflow.result_resource_ids,
                metadata__formalDisplay__version=1,
            ).exists()
            if published:
                checks[code_name] = True
        if (
            len(checks) == len(cases)
            and (root / "monitoring-browser-accepted").is_file()
        ):
            print(json.dumps({"accepted": True, "checks": checks}, ensure_ascii=False))
            return
        time.sleep(1.3)
    raise RuntimeError(f"浏览器及正式登记验收未完成：{checks}")


if __name__ == "__main__":
    main()
