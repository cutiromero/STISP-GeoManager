"""统一full发布的遥感监测候选验收钩子；业务写入均回滚。"""

import argparse
import json
import os
from pathlib import Path
import sys
import tomllib

# CONFIGURATION
PROJECT_CODE = "06"
ACTOR_USERNAME = "admin"
CONTEXT_PATH = Path(__file__).resolve().parent / "candidate-context.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, default=CONTEXT_PATH)
    context = json.loads(parser.parse_args().context.read_text())
    root, code = Path(context["root"]).resolve(), Path(context["code"]).resolve()
    config = Path(context["config"]).resolve()
    assert code.is_relative_to(root) and config.is_relative_to(root)
    raw = tomllib.loads(config.read_text())
    for name in ("app_data", "research_data_root"):
        assert Path(raw["application"]["storage"][name]).resolve().is_relative_to(root)
    assert (code / ".runtime/config-path").read_text().strip() == str(config)
    os.chdir(code / "backend")
    sys.path.insert(0, str(code / "backend"))
    os.environ["DJANGO_SETTINGS_MODULE"] = "geomanager.settings"
    import django

    django.setup()
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.core.exceptions import ValidationError
    from django.db import transaction
    from django.test import Client
    from apps.ecology.models import RemoteSensingProduct
    from apps.ecology.monitoring import normalize_product
    from apps.projects.context import ProjectScope, project_scope, is_superadmin
    from apps.projects.features import set_feature
    from apps.projects.models import Project, ProjectFeature, ProjectFeatureSetting

    assert Path(settings.DATABASES["default"]["NAME"]).resolve().is_relative_to(root)
    checks = {"candidateStorageIsolated": True}
    anonymous = Client(HTTP_HOST="127.0.0.1")
    assert (
        anonymous.get(
            "/api/ecology/monitoring/?scene=spartina", HTTP_X_PROJECT_ID="1"
        ).status_code
        == 401
    )
    checks["anonymousDenied"] = True
    actor = get_user_model().objects.get(username=ACTOR_USERNAME, is_active=True)
    assert is_superadmin(actor)
    project = Project.objects.get(code=PROJECT_CODE, is_active=True)
    feature = ProjectFeature.objects.get(key="ecology_monitor")
    before = list(
        ProjectFeatureSetting.objects.filter(project=project, feature=feature).values(
            "enabled", "config"
        )
    )
    before_count = RemoteSensingProduct.objects.count()
    with (
        transaction.atomic(),
        project_scope(ProjectScope((project.pk,), project.pk, actor.pk)),
    ):
        set_feature(
            actor,
            feature,
            project=project,
            enabled=True,
            config=json.loads(
                (code / "examples/monitoring/project-config.json").read_text()
            ),
        )
        client = Client(HTTP_HOST="127.0.0.1")
        client.force_login(actor)
        assert client.get("/api/ecology/monitoring/?scene=spartina").status_code == 400
        checks["explicitProjectRequired"] = True
        for scene in ("spartina", "wildfire"):
            response = client.get(
                "/api/ecology/monitoring/",
                {"scene": scene},
                HTTP_X_PROJECT_ID=str(project.pk),
            )
            assert response.status_code == 200, response.content
            value = response.json()
            assert value["scene"] == scene and value["projectId"] == project.pk
            assert all(
                item["resource"]["projectTagId"] == project.pk
                for item in value["items"]
            )
        checks["projectSceneReads"] = True
        assert (
            client.get(
                "/api/ecology/monitoring/?scene=unknown",
                HTTP_X_PROJECT_ID=str(project.pk),
            ).status_code
            == 400
        )
        checks["unknownSceneDenied"] = True
        sample = normalize_product(
            json.loads((code / "examples/monitoring/spartina-product.json").read_text())
        )
        assert (
            sample["observedStart"] is None and sample["statistics"]["area_ha"] is None
        )
        checks["unknownTimeAndAreaRetained"] = True
        sample["timing"].update(validStart="2026-11-14", validEnd="2026-11-21")
        try:
            normalize_product(sample)
        except ValidationError:
            checks["unprovenForecastDenied"] = True
        else:
            raise AssertionError("无时效依据的预报被接受")
        transaction.set_rollback(True)
    assert (
        list(
            ProjectFeatureSetting.objects.filter(
                project=project, feature=feature
            ).values("enabled", "config")
        )
        == before
    )
    assert RemoteSensingProduct.objects.count() == before_count
    checks["temporaryContentRolledBack"] = True
    print(json.dumps({"accepted": True, "checks": checks}, ensure_ascii=False))


if __name__ == "__main__":
    main()
