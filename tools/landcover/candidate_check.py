"""Run real five-model inference in the standard release candidate's storage."""

import argparse
import io
import json
import os
from pathlib import Path
import sys
import time
import tomllib

# ==================== CONFIGURATION ====================
PROJECT_CODE = "gd"
ACTOR_USERNAME = "admin"
ORIGINAL = Path(
    "/root/autodl-tmp/geomanager-data-20260919/research/projects/2/raster/original/imported/landcover-handoff-20261114/region_01.tif"
)
WINDOW_SIZE = 1024
TIMEOUT_SECONDS = 300
CONTEXT_PATH = Path(__file__).with_name("candidate-context.json")
# =======================================================


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, default=CONTEXT_PATH)
    context = json.loads(parser.parse_args().context.read_text())
    root, code, config = (
        Path(context[key]).resolve() for key in ("root", "code", "config")
    )
    assert code.is_relative_to(root) and config.is_relative_to(root)
    raw = tomllib.loads(config.read_text())
    for key in ("app_data", "research_data_root"):
        assert Path(raw["application"]["storage"][key]).resolve().is_relative_to(root)
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
    from apps.compute.models import ComputeTask, AlgorithmVersion
    from apps.core.storage import app_path
    from apps.ecology.monitoring import monitoring_snapshot
    from apps.projects.context import ProjectScope, project_scope
    from apps.projects.models import Project
    from apps.raster.services.importer import import_raster_file

    assert Path(settings.DATABASES["default"]["NAME"]).resolve().is_relative_to(root)
    source = root / "research/landcover-candidate-input.tif"
    gdal.UseExceptions()
    dataset = gdal.Translate(
        str(source),
        str(ORIGINAL),
        srcWin=[0, 0, WINDOW_SIZE, WINDOW_SIZE],
        creationOptions=["COMPRESS=DEFLATE", "TILED=YES"],
    )
    dataset.Close()
    actor = get_user_model().objects.get(username=ACTOR_USERNAME, is_active=True)
    project = Project.objects.get(code=PROJECT_CODE, is_active=True)
    scope = ProjectScope((project.pk,), project.pk, actor.pk, True)

    def register(stage, **options):
        stream = io.StringIO()
        call_command(
            "register_landcover",
            project=PROJECT_CODE,
            actor=ACTOR_USERNAME,
            stage=stage,
            stdout=stream,
            **options,
        )
        return json.loads(stream.getvalue().strip().splitlines()[-1])

    with project_scope(scope):
        raster = import_raster_file(
            source, name="地表覆盖候选小窗", uploader_id=actor.pk
        )
        registered = register("operator")
        trial = register("trial", resource_id=raster.data_resource_id)
    started = time.monotonic()
    while time.monotonic() - started < TIMEOUT_SECONDS:
        with project_scope(scope):
            task = ComputeTask.objects.get(pk=trial["taskId"])
        if task.status in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(1)
    assert task.status == "succeeded", {
        "status": task.status,
        "stage": task.stage,
        "error": task.error,
        "failure": task.failure,
    }
    with project_scope(scope):
        output = task.outputs.get(key="classification")
        assert output.metadata["rasterKind"] == "categorical"
        assert output.metadata["qualityCheck"]["status"] == "passed"
        facts = output.metadata["knowledgeFacts"]["landcover"]
        assert len(facts["models"]) == 5 and len(facts["statistics"]) == 6
        assert facts["priority"] == ["建筑", "水体", "耕地", "林地", "道路"]
        assert (
            output.metadata["width"] == WINDOW_SIZE
            and output.metadata["height"] == WINDOW_SIZE
        )
        assert app_path(output.path).is_file()
        register("publish", publish_updates=True)
        snapshot = monitoring_snapshot(actor, "landcover")
        assert snapshot["businessFlow"]["definitionId"]
        version = AlgorithmVersion.objects.get(pk=registered["versionId"])
        assert version.status == "published"
    client = Client(HTTP_HOST="127.0.0.1")
    assert (
        client.get(
            "/api/ecology/monitoring/?scene=landcover",
            HTTP_X_PROJECT_ID=str(project.pk),
        ).status_code
        == 401
    )
    client.force_login(actor)
    assert (
        client.get(
            "/api/ecology/monitoring/?scene=landcover",
            HTTP_X_PROJECT_ID=str(project.pk),
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/ecology/monitoring/?scene=landcover", HTTP_X_PROJECT_ID="1"
        ).status_code
        == 403
    )
    print(
        json.dumps(
            {
                "accepted": True,
                "checks": {
                    "candidateStorageIsolated": True,
                    "realFiveModelTrial": True,
                    "sourceGridAndPalette": True,
                    "publishedFlow": True,
                    "projectAndAnonymousIsolation": True,
                },
                "elapsedSeconds": round(time.monotonic() - started, 2),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
