"""Real native-cube observation in the standard isolated release candidate."""

import argparse
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time

# CONFIGURATION
PROJECT_CODE = "06"
ACTOR = "admin"
ORIGINAL = Path(
    "/root/autodl-tmp/geomanager-data-20260919/research/projects/13/raster/original/imported/wildfire-handoff-20261114/seasfire_v0.4.zarr"
)
PARAMETERS = {
    "product": "gwis_ba",
    "time_index": 873,
    "history": 3,
    "west": 112,
    "south": -44,
    "east": 154,
    "north": -10,
}
TIMEOUT = 300


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", type=Path, required=True)
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
    from django.db import transaction
    from django.db.models import F
    from apps.projects.context import ProjectScope, project_scope
    from apps.projects.models import Project
    from apps.catalog.models import DataResource, DataResourceGroup
    from apps.compute.cube_inputs import source_dependencies
    from apps.compute.native_cube_reader import Cube
    from apps.compute.models import ComputeTask
    from apps.compute.services import submit, request_output_import
    from apps.core.storage import raster_source_path, table_data_path
    from apps.ecology.monitoring import monitoring_snapshot
    from apps.ecology.wildfire import observation_catalog

    assert Path(settings.DATABASES["default"]["NAME"]).resolve().is_relative_to(root)
    actor = get_user_model().objects.get(username=ACTOR, is_active=True)
    project = Project.objects.get(code=PROJECT_CODE, is_active=True)
    scope = ProjectScope((project.pk,), project.pk, actor.pk, True)

    def register(stage, **values):
        stream = io.StringIO()
        call_command(
            "register_wildfire",
            project=PROJECT_CODE,
            actor=ACTOR,
            stage=stage,
            stdout=stream,
            **values,
        )
        return json.loads(stream.getvalue().strip().splitlines()[-1])

    def wait(task_id):
        started = time.monotonic()
        while time.monotonic() - started < TIMEOUT:
            with project_scope(scope):
                task = ComputeTask.objects.get(pk=task_id)
            if task.status not in ["queued", "validating", "running", "cancelling"]:
                break
            time.sleep(1)
        assert task.status == "succeeded", {
            "status": task.status,
            "error": task.error,
            "failure": task.failure,
        }
        return task

    original = Cube(ORIGINAL)
    plan = original.plan("gwis_ba", 873, [112, -44, 154, -10], 3)
    with project_scope(scope):
        target = raster_source_path("wildfire-candidate.zarr")
        target.mkdir(parents=True, exist_ok=True)
        sources = [
            ORIGINAL / name for name in [".zmetadata", ".zgroup", ".zattrs"]
        ] + source_dependencies(ORIGINAL, plan)
        for source in sources:
            destination = target / source.relative_to(ORIGINAL)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        group = DataResourceGroup.objects.create(name="野火候选真实子集")
        with transaction.atomic():
            Project.objects.filter(pk=project.pk).update(name=F("name"))
            cube = DataResource.objects.create(
                name="野火候选原生观测子集",
                code="wildfire-seasfire-cube-candidate",
                data_type="raster",
                file_format="ZARR",
                storage_path="original/wildfire-candidate.zarr",
                coordinate_system="EPSG:4326",
                inventory_group=group,
                item_count=966,
                size_bytes=sum(
                    path.stat().st_size for path in target.rglob("*") if path.is_file()
                ),
            )
            time_table = "wildfire_seasfire_time_candidate"
            path = table_data_path("data.sqlite")
            path.parent.mkdir(parents=True, exist_ok=True)
            masks = {
                name: original.read(name)
                for name in [
                    "gwis_ba_valid_mask",
                    "gfed_ba_valid_mask",
                    "fcci_ba_valid_mask",
                ]
            }
            with sqlite3.connect(path) as db:
                db.execute(
                    "CREATE TABLE "
                    + time_table
                    + " (time_index INTEGER,date TEXT,gwis_ba_valid_mask INTEGER,gfed_ba_valid_mask INTEGER,fcci_ba_valid_mask INTEGER)"
                )
                db.executemany(
                    "INSERT INTO " + time_table + " VALUES (?,?,?,?,?)",
                    [
                        (
                            index,
                            day.isoformat(),
                            *[int(masks[name][index]) for name in masks],
                        )
                        for index, day in enumerate(original.dates)
                    ],
                )
            DataResource.objects.create(
                name="候选真实时间索引",
                code="wildfire-candidate-time",
                data_type="table",
                file_format="SQLITE",
                storage_path=time_table,
                inventory_group=group,
                item_count=966,
            )
            registered = register("operator")
            trial = register(
                "trial",
                inputs_json=json.dumps({"cube": cube.pk}),
                parameters_json=json.dumps(PARAMETERS),
            )
    task = wait(trial["taskId"])
    with project_scope(scope):
        facts = task.outputs.get(key="observation").metadata["knowledgeFacts"][
            "wildfireObservation"
        ]
        assert (
            facts["statistics"]["burned_area_ha"] > 0
            and facts["current"]["observedEnd"] == "2019-12-31"
        )
        published = register("publish", publish_updates=True)
        task = submit(
            actor,
            {
                "name": "野火候选真实观测",
                "versionId": registered["versionId"],
                "trial": False,
                "idempotencyKey": "wildfire-observe-candidate",
                "inputs": {"cube": cube.pk},
                "parameters": PARAMETERS,
            },
        )
    task = wait(task.pk)
    with project_scope(scope):
        records = [
            request_output_import(actor, output)
            for output in task.outputs.filter(
                key__in=["observation", "classification", "statistics", "series"]
            )
        ]
    started = time.monotonic()
    while time.monotonic() - started < TIMEOUT:
        for record in records:
            record.refresh_from_db()
        if all(record.status == "ready" for record in records):
            break
        if any(record.status == "failed" for record in records):
            raise AssertionError([record.error for record in records])
        time.sleep(1)
    assert all(record.status == "ready" for record in records)
    with project_scope(scope):
        snapshot = monitoring_snapshot(actor, "wildfire")
        product = next(
            item
            for item in snapshot["items"]
            if item.get("provenance", {}).get("taskId") == str(task.pk)
        )
        assert (
            product["kind"] == "observation"
            and product["model"] is None
            and product["observation"]["series"]
        )
        assert {row["role"] for row in product["attachments"]} == {
            "classification",
            "statistics",
            "series",
        }
        assert snapshot["businessFlow"]["definitionId"] == published["flowId"]
        assert len(observation_catalog(actor)["times"]) == 966
    proof = {
        "ready": True,
        "candidateStorageIsolated": True,
        "realNativeCube": True,
        "realDatesAndUnits": True,
        "standardImports": True,
        "publishedFlow": True,
        "statistics": product["statistics"],
    }
    (root / "wildfire-acceptance.json").write_text(
        json.dumps(proof, ensure_ascii=False, indent=2)
    )
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == "__main__":
    main()
