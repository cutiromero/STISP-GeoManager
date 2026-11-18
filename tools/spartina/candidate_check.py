"""Real RF inference and standard imports in the release candidate only."""

import argparse
import io
import json
import os
import runpy
from pathlib import Path
import sys
import time
from types import SimpleNamespace

# CONFIGURATION
PROJECT_CODE = "06"
ACTOR = "admin"
ORIGINAL_ROOT = Path(
    "/root/autodl-tmp/geomanager-data-20260919/research/projects/13/raster/original/imported/spartina-handoff-20261114"
)
POINT = (121.92, 31.24)
SIZE = 64
TIMEOUT = 360


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
    from django.test import Client
    from apps.compute.models import ComputeTask
    from apps.compute.services import submit, request_output_import
    from apps.compute.ml_runtime import binding
    from apps.core.browser_sessions import prepare_browser_session
    from apps.ecology.monitoring import monitoring_snapshot
    from apps.ecology.official_monitoring import register_output
    from apps.projects.context import project_scope, ProjectScope
    from apps.projects.models import Project
    from apps.raster.services.importer import import_raster_file
    import rasterio
    from rasterio.windows import Window

    assert Path(settings.DATABASES["default"]["NAME"]).resolve().is_relative_to(root)
    actor = get_user_model().objects.get(username=ACTOR, is_active=True)
    project = Project.objects.get(code=PROJECT_CODE, is_active=True)
    scope = ProjectScope((project.pk,), project.pk, actor.pk, True)

    def register(stage, **options):
        output = io.StringIO()
        call_command(
            "register_spartina",
            project=PROJECT_CODE,
            actor=ACTOR,
            stage=stage,
            stdout=output,
            **options,
        )
        return json.loads(output.getvalue().strip().splitlines()[-1])

    def wait(task_id):
        start = time.monotonic()
        while time.monotonic() - start < TIMEOUT:
            with project_scope(scope):
                task = ComputeTask.objects.get(pk=task_id)
            if task.status not in ["queued", "validating", "running", "cancelling"]:
                break
            time.sleep(1)
        assert task.status == "succeeded", {
            "status": task.status,
            "stage": task.stage,
            "error": task.error,
            "failure": task.failure,
        }
        return task

    inputs = {}
    bounds = None
    with project_scope(scope):
        runpy.run_path(str(code / "tools/monitoring/candidate_assets.py"))[
            "stage_published_package"
        ](code / "examples/compute/spartina-rf", root)
        manifest = json.loads(
            (code / "examples/compute/spartina-rf/operator.yaml").read_text()
        )
        binding(manifest, project.pk)
        for role, month in [("march", "03"), ("august", "08"), ("december", "12")]:
            path = root / "research" / f"spartina-{month}.tif"
            with rasterio.open(ORIGINAL_ROOT / f"merged_sat_2025{month}.tif") as src:
                row, col = src.index(*POINT)
                window = Window(col, row, SIZE, SIZE)
                profile = {
                    **src.profile,
                    "driver": "GTiff",
                    "width": SIZE,
                    "height": SIZE,
                    "transform": src.window_transform(window),
                    "compress": "deflate",
                    "tiled": True,
                    "blockxsize": 32,
                    "blockysize": 32,
                }
                with rasterio.open(path, "w", **profile) as dst:
                    dst.write(src.read(window=window))
                    for index, name in enumerate(src.descriptions, 1):
                        if name:
                            dst.set_band_description(index, name)
                    bounds = list(dst.bounds)
            with transaction.atomic():
                Project.objects.filter(pk=project.pk).update(name=F("name"))
                raster = import_raster_file(
                    path,
                    name=f"互花米草候选2025{month}",
                    uploader_id=actor.pk,
                    raster_kind="imagery",
                )
                resource = raster.data_resource
                resource.code = f"spartina-candidate-2025{month}"
                resource.save(update_fields=["code"])
                from apps.catalog.monitoring_metadata import update_metadata

                update_metadata(
                    actor,
                    resource,
                    {
                        "usages": [{"scene": "spartina", "purpose": "input"}],
                        "collectionKey": "spartina-candidate",
                        "family": "raster",
                        "startsAt": f"2025-{month}-01",
                        "endsAt": f"2025-{month}-01",
                        "precision": "day",
                    },
                )
                inputs[role] = raster.data_resource_id
        params = dict(zip(["west", "south", "east", "north"], bounds))
        registered = register("operator")
        trial = register(
            "trial", inputs_json=json.dumps(inputs), parameters_json=json.dumps(params)
        )
    task = wait(trial["taskId"])
    with project_scope(scope):
        facts = task.outputs.get(key="classification").metadata["knowledgeFacts"][
            "spartina"
        ]
        assert facts["validPixelCount"] > 0 and facts["targetPixelCount"] > 0
        with transaction.atomic():
            Project.objects.filter(pk=project.pk).update(name=F("name"))
            published = register("publish", publish_updates=True)
        actual = submit(
            actor,
            {
                "name": "互花米草候选实际成果",
                "versionId": registered["versionId"],
                "trial": False,
                "idempotencyKey": "spartina-candidate-actual",
                "inputs": inputs,
                "parameters": params,
            },
        )
    task = wait(actual.pk)
    with project_scope(scope), transaction.atomic():
        Project.objects.filter(pk=project.pk).update(name=F("name"))
        records = [
            request_output_import(actor, output, output.label)
            for output in task.outputs.filter(
                key__in=["classification", "probability", "statistics", "original"]
            )
        ]
    start = time.monotonic()
    while time.monotonic() - start < TIMEOUT:
        for record in records:
            record.refresh_from_db()
        if all(record.status == "ready" for record in records):
            break
        if any(record.status == "failed" for record in records):
            raise AssertionError([(str(record.pk), record.error) for record in records])
        time.sleep(1)
    assert all(record.status == "ready" for record in records)
    with project_scope(scope):
        register_output(
            actor,
            next(
                row.output_id for row in records if row.output.key == "classification"
            ),
        )
        snapshot = monitoring_snapshot(actor, "spartina")
        product = next(
            item
            for item in snapshot["items"]
            if item.get("provenance", {}).get("taskId") == str(task.pk)
        )
        assert set(row["role"] for row in product["attachments"]) == {
            "probability",
            "statistics",
            "original",
        }
        assert product["statistics"]["area_ha"] > 0
        assert snapshot["businessFlow"]["definitionId"] == published["flowId"]
        assert set(row["id"] for row in snapshot["inputResources"]) >= set(
            inputs.values()
        )
    client = Client(HTTP_HOST="127.0.0.1")
    assert (
        client.get(
            "/api/ecology/monitoring/?scene=spartina", HTTP_X_PROJECT_ID="1"
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/ecology/monitoring/?scene=spartina", HTTP_X_PROJECT_ID=str(project.pk)
        ).status_code
        == 404
    )
    client.force_login(actor)
    session = client.session
    prepare_browser_session(SimpleNamespace(session=session))
    session.save()
    assert (
        client.post(
            "/api/auth/browser-session/",
            {
                "action": "start",
                "pageId": "spartina_candidate",
                "token": "b" * 64,
                "sequence": 1,
            },
            content_type="application/json",
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/ecology/monitoring/?scene=spartina", HTTP_X_PROJECT_ID=str(project.pk)
        ).status_code
        == 200
    )
    result = {
        "ready": True,
        "candidateStorageIsolated": True,
        "realRFInference": True,
        "originalGridAndPalette": True,
        "standardImports": True,
        "relatedResources": True,
        "publishedFlow": True,
        "anonymousIsolation": True,
        "statistics": product["statistics"],
    }
    (root / "spartina-acceptance.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
