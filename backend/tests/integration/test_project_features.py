import importlib
import json

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test.utils import CaptureQueriesContext

from apps.audit.models import OperationLog
from apps.projects.models import (
    Project,
    ProjectFeature,
    ProjectFeatureSetting,
    ProjectMembership,
)

MONITOR_CONFIG = {
    "title": "独立项目监测",
    "source": "tarim_poplar_mock",
    "initialView": {"center": [100, 35], "zoom": 3, "regionZoom": 6},
}


@pytest.fixture
def actors():
    users = get_user_model()
    admin = users.objects.create_superuser("feature-admin")
    user = users.objects.create_user("feature-member")
    staff = users.objects.create_user("feature-staff", is_staff=True)
    project = Project.objects.create(code="feature-test", name="测试项目")
    other = Project.objects.create(code="feature-other", name="其他项目")
    ProjectMembership.objects.create(project=project, user=user)
    feature, _ = ProjectFeature.objects.get_or_create(key="ecology_monitor")
    feature.globally_enabled = False
    feature.save()
    return admin, user, staff, project, other, feature


def project_item(client, project):
    return next(
        item
        for item in client.get("/api/projects/").json()["items"]
        if item["id"] == project.pk
    )


def test_enable_disable_global_and_config_isolation(client, actors):
    admin, _, _, project, other, _ = actors
    client.force_login(admin)
    route = f"/api/projects/{project.pk}/features/ecology_monitor/"
    assert project_item(client, project)["enabledFeatures"] == []
    response = client.post(
        route,
        {"enabled": True, "config": MONITOR_CONFIG},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["enabledFeatures"] == ["ecology_monitor"]
    assert response.json()["monitorConfig"] == MONITOR_CONFIG
    assert project_item(client, other)["monitorConfig"] is None
    response = client.post(route, {"enabled": False}, content_type="application/json")
    assert response.status_code == 200
    assert response.json()["enabledFeatures"] == []
    assert response.json()["monitorConfig"] is None
    other_route = f"/api/projects/{other.pk}/features/ecology_monitor/"
    assert (
        client.post(
            other_route, {"enabled": True}, content_type="application/json"
        ).status_code
        == 200
    )
    global_route = "/api/projects/features/ecology_monitor/"
    assert (
        client.post(
            global_route, {"enabled": True}, content_type="application/json"
        ).status_code
        == 200
    )
    assert project_item(client, project)["monitorConfig"] == MONITOR_CONFIG
    assert project_item(client, other)["enabledFeatures"] == ["ecology_monitor"]
    assert project_item(client, other)["monitorConfig"] is None
    future = Project.objects.create(code="feature-future", name="将来项目")
    assert project_item(client, future)["enabledFeatures"] == ["ecology_monitor"]
    future.is_active = False
    future.save()
    assert project_item(client, future)["enabledFeatures"] == []
    assert (
        client.post(
            global_route, {"enabled": False}, content_type="application/json"
        ).status_code
        == 200
    )
    assert project_item(client, project)["enabledFeatures"] == []
    assert project_item(client, other)["enabledFeatures"] == ["ecology_monitor"]
    assert (
        client.post(
            other_route, {"enabled": False}, content_type="application/json"
        ).json()["enabledFeatures"]
        == []
    )
    assert (
        client.post(route, {"enabled": True}, content_type="application/json").json()[
            "monitorConfig"
        ]
        == MONITOR_CONFIG
    )
    assert (
        client.post(route, {"config": None}, content_type="application/json").json()[
            "monitorConfig"
        ]
        is None
    )
    logs = OperationLog.objects.filter(module="项目功能")
    assert logs.count() == 8
    assert all(
        log.user_id == admin.pk and log.target_code == "ecology_monitor" for log in logs
    )
    assert any("全局 False -> True" in log.message for log in logs)
    assert any("项目 feature-test" in log.message for log in logs)


@pytest.mark.parametrize("actor_index", [1, 2])
def test_only_superadmin_can_modify_and_global_does_not_grant_access(
    client, actors, actor_index
):
    _, user, _, project, other, feature = actors
    feature.globally_enabled = True
    feature.save()
    client.force_login(actors[actor_index])
    for route in [
        f"/api/projects/{project.pk}/features/ecology_monitor/",
        "/api/projects/features/ecology_monitor/",
    ]:
        assert (
            client.post(
                route, {"enabled": False}, content_type="application/json"
            ).status_code
            == 403
        )
    assert not OperationLog.objects.filter(module="项目功能").exists()
    client.force_login(user)
    data = client.get("/api/projects/").json()
    assert other.pk not in {item["id"] for item in data["items"]}
    assert data["featureCatalog"] == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"enabled": "false"},
        {"enabled": 1},
        {"config": []},
        {"config": {**MONITOR_CONFIG, "source": "unknown"}},
        {"config": {**MONITOR_CONFIG, "title": " "}},
        {
            "config": {
                **MONITOR_CONFIG,
                "initialView": {"center": [181, 0], "zoom": 3, "regionZoom": 4},
            }
        },
        {
            "config": {
                **MONITOR_CONFIG,
                "initialView": {"center": [0, False], "zoom": 3, "regionZoom": 4},
            }
        },
    ],
)
def test_invalid_settings_are_atomic(client, actors, body):
    admin, _, _, project, _, _ = actors
    client.force_login(admin)
    response = client.post(
        f"/api/projects/{project.pk}/features/ecology_monitor/",
        body,
        content_type="application/json",
    )
    assert response.status_code == 400
    assert not ProjectFeatureSetting.objects.filter(project=project).exists()
    assert not OperationLog.objects.filter(module="项目功能").exists()


def test_unknown_feature_and_global_payload(client, actors):
    admin = actors[0]
    client.force_login(admin)
    assert (
        client.post(
            "/api/projects/features/unknown/",
            {"enabled": True},
            content_type="application/json",
        ).status_code
        == 404
    )
    for data in [{}, {"enabled": "false"}, {"enabled": True, "config": None}]:
        assert (
            client.post(
                "/api/projects/features/ecology_monitor/",
                data,
                content_type="application/json",
            ).status_code
            == 400
        )


def test_command_register_enable_disable_config_and_audit(actors, tmp_path):
    admin, user, _, project, _, _ = actors
    call_command(
        "project_feature", "future_module", actor=admin.username, register=True
    )
    assert ProjectFeature.objects.get(key="future_module").globally_enabled is False
    call_command(
        "project_feature",
        "future_module",
        actor=admin.username,
        project=project.code,
        enable=True,
    )
    assert ProjectFeatureSetting.objects.get(
        project=project, feature__key="future_module"
    ).enabled
    config_file = tmp_path / "monitor.json"
    config_file.write_text(json.dumps(MONITOR_CONFIG), encoding="utf-8")
    call_command(
        "project_feature",
        "ecology_monitor",
        actor=admin.username,
        project=project.code,
        enable=True,
        config=config_file,
    )
    assert (
        ProjectFeatureSetting.objects.get(
            project=project, feature__key="ecology_monitor"
        ).config
        == MONITOR_CONFIG
    )
    call_command(
        "project_feature",
        "ecology_monitor",
        actor=admin.username,
        all_projects=True,
        enable=True,
    )
    call_command(
        "project_feature",
        "ecology_monitor",
        actor=admin.username,
        all_projects=True,
        disable=True,
    )
    call_command(
        "project_feature",
        "ecology_monitor",
        actor=admin.username,
        project=project.code,
        disable=True,
    )
    assert not ProjectFeatureSetting.objects.get(
        project=project, feature__key="ecology_monitor"
    ).enabled
    with pytest.raises(CommandError, match="超级管理员"):
        call_command(
            "project_feature",
            "ecology_monitor",
            actor=user.username,
            all_projects=True,
            enable=True,
        )
    assert OperationLog.objects.filter(module="项目功能", user=admin).count() == 6


@pytest.mark.efficiency
def test_feature_serialization_does_not_query_per_project(client, actors):
    client.force_login(actors[0])
    for number in range(15):
        Project.objects.create(code=f"feature-bulk-{number}", name=f"批量项目{number}")
    with CaptureQueriesContext(connection) as queries:
        assert client.get("/api/projects/").status_code == 200
    feature_reads = [
        query for query in queries if 'FROM "projects_projectfeature' in query["sql"]
    ]
    assert len(feature_reads) == 3


def test_audit_failure_rolls_back_setting(client, actors, monkeypatch):
    admin, _, _, project, _, _ = actors
    client.force_login(admin)

    def fail_audit(*args, **kwargs):
        raise RuntimeError("审计不可用")

    monkeypatch.setattr("apps.projects.features.log_operation", fail_audit)
    with pytest.raises(RuntimeError, match="审计不可用"):
        client.post(
            f"/api/projects/{project.pk}/features/ecology_monitor/",
            {"enabled": True},
            content_type="application/json",
        )
    assert not ProjectFeatureSetting.objects.filter(project=project).exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("has_target", [True, False])
def test_existing_database_migration_is_safe_and_idempotent(has_target):
    old = [("projects", "0002_public_project_name")]
    new = [("projects", "0003_project_features")]
    executor = MigrationExecutor(connection)
    try:
        executor.migrate(old)
        old_apps = executor.loader.project_state(old).apps
        projects = old_apps.get_model("projects", "Project")
        target = (
            projects.objects.create(code="05", name="已重命名的胡杨项目")
            if has_target
            else None
        )
        other = projects.objects.create(
            code="migration-other", name="保留其他项目", description="不得改动"
        )
        executor = MigrationExecutor(connection)
        executor.migrate(new)
        apps = executor.loader.project_state(new).apps
        settings = apps.get_model("projects", "ProjectFeatureSetting")
        feature = apps.get_model("projects", "ProjectFeature").objects.get(
            key="ecology_monitor"
        )
        assert feature.globally_enabled is False
        assert not settings.objects.filter(project_id=other.pk).exists()
        assert projects.objects.get(pk=other.pk).description == "不得改动"
        if target is not None:
            row = settings.objects.get(project_id=target.pk)
            assert row.enabled is True
            assert row.config["source"] == "tarim_poplar_mock"
            assert row.config["title"] == "塔里木河流域胡杨林生态监测"
            assert row.config["initialView"] == {
                "center": [84, 39.9],
                "zoom": 2.05,
                "regionZoom": 5.15,
            }
            row.enabled = False
            row.save()
        migration = importlib.import_module(
            "apps.projects.migrations.0003_project_features"
        )
        with connection.schema_editor() as editor:
            migration.seed_monitor(apps, editor)
        assert settings.objects.count() == (1 if has_target else 0)
        if target is not None:
            assert settings.objects.get(project_id=target.pk).enabled is False
    finally:
        MigrationExecutor(connection).migrate([("projects", "0004_project_deleted_at")])
