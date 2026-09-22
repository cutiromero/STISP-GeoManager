import io
from dataclasses import replace

import pytest
from PIL import Image
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from apps.content.models import Article
from apps.content.views import store_asset
from apps.projects.models import Project


@pytest.fixture
def people(db):
    users = get_user_model()
    admin = users.objects.create_superuser("public-navigation-admin")
    researcher = users.objects.create_user("public-navigation-researcher")
    private = Project.objects.create(name="研究项目", code="public-nav-private")
    return admin, researcher, private


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "head", "post"])
@pytest.mark.parametrize(
    "url",
    [
        "/api/catalog/resources/",
        "/api/admin/data/resources/",
        "/api/catalog/workspaces/",
        "/api/catalog/map-compositions/",
        "/api/catalog/results/",
        "/api/raster/datasets/",
    ],
)
def test_every_business_request_rejects_aggregate_scope(client, people, method, url):
    for user in (None, people[0], people[1]):
        client.logout()
        if user:
            client.force_login(user)
        for kwargs in (
            {"HTTP_X_PROJECT_ID": "all"},
            {"QUERY_STRING": "projectTagId=all"},
        ):
            response = getattr(client, method)(url, **kwargs)
            assert response.status_code == 400


@pytest.mark.django_db
def test_public_project_name_and_membership_invariants(client, people):
    public = Project.objects.get(pk=1)
    assert (public.name, public.code, public.is_default, public.is_active) == (
        "公开",
        "default",
        True,
        True,
    )
    assert client.get("/api/projects/").json()["items"][0]["name"] == "公开"
    client.force_login(people[0])
    for data in ({"name": "私有"}, {"name": "公开", "isActive": False}):
        assert (
            client.post(
                "/api/projects/1/", data, content_type="application/json"
            ).status_code
            == 400
        )
    assert client.get("/api/projects/", HTTP_X_PROJECT_ID="all").status_code == 200


@pytest.mark.django_db
def test_public_news_detail_media_and_editing_ignore_business_project(
    client, people, settings, tmp_path
):
    admin, researcher, private = people
    settings.PROJECT_CONFIG = replace(
        settings.PROJECT_CONFIG,
        app_data=tmp_path / "app",
        research_data_root=tmp_path / "research",
    )
    published = Article.objects.create(
        kind="news", title="团队动态", category="学术会议", status="published"
    )
    draft = Article.objects.create(kind="news", title="未发布", category="学术会议")
    archived = Article.objects.create(
        kind="news", title="已下架", category="学术会议", status="archived"
    )
    blob = io.BytesIO()
    Image.new("RGB", (3, 3)).save(blob, "PNG")
    assets = [
        store_asset(article, "cover.png", blob.getvalue())
        for article in (published, draft, archived)
    ]
    for user in (None, researcher):
        client.logout()
        if user:
            client.force_login(user)
        for selected in ("1", str(private.pk), "999999", "all"):
            headers = {"HTTP_X_PROJECT_ID": selected}
            response = client.get("/api/content/articles/?kind=news", **headers)
            assert [a["id"] for a in response.json()["items"]] == [published.id]
            assert (
                client.get(
                    f"/api/content/articles/{published.id}/", **headers
                ).status_code
                == 200
            )
            # Historical asset links with project parameters still address the same public file.
            response = client.get(
                f"/api/content/assets/{assets[0].id}/?projectTagId={private.id}",
                **headers,
            )
            assert response.status_code == 200
            assert b"".join(response.streaming_content) == blob.getvalue()
            for article, asset in zip((draft, archived), assets[1:]):
                assert (
                    client.get(
                        f"/api/content/articles/{article.id}/", **headers
                    ).status_code
                    == 404
                )
                assert (
                    client.get(
                        f"/api/content/assets/{asset.id}/", **headers
                    ).status_code
                    == 404
                )
            assert (
                client.post(
                    "/api/content/articles/",
                    {"kind": "news"},
                    content_type="application/json",
                    **headers,
                ).status_code
                == 403
            )
    client.force_login(admin)
    created = client.post(
        "/api/content/articles/",
        {
            "kind": "news",
            "title": "任意项目下编写",
            "category": "团队动态",
            "status": "published",
        },
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(private.pk),
    )
    assert created.status_code == 201
    assert created.json()["projectTagId"] == 1
    with transaction.atomic(), pytest.raises(IntegrityError):
        Article.objects.create(
            kind="news",
            title="不允许私有归属",
            category="团队动态",
            project_tag=private,
        )


@pytest.mark.django_db(transaction=True)
def test_public_content_migration_preserves_records_paths_and_seed_collisions():
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    before = [("content", "0003_alter_article_owner"), ("projects", "0001_initial")]
    try:
        executor.migrate(before)
        old = executor.loader.project_state(before).apps
        projects = old.get_model("projects", "Project")
        projects.objects.get_or_create(
            pk=1, defaults={"name": "默认", "code": "default", "is_default": True}
        )
        private = projects.objects.create(name="原私有", code="old-private")
        articles = old.get_model("content", "Article")
        public = articles.objects.create(
            kind="news", title="公开原文", category="会议", seed_key="same"
        )
        hidden = articles.objects.create(
            kind="news",
            title="迁移原文",
            body="原始正文",
            category="会议",
            status="published",
            seed_key="same",
            project_tag_id=private.pk,
        )
        asset = old.get_model("content", "Asset").objects.create(
            article=hidden,
            project_tag_id=private.pk,
            name="原附件.png",
            path=f"projects/{private.pk}/content/{hidden.pk}/original.png",
            mime_type="image/png",
            checksum="a" * 64,
            size_bytes=3,
        )
        articles.objects.filter(pk=hidden.pk).update(cover_asset_id=asset.pk)
        MigrationExecutor(connection).migrate(latest)
        migrated = Article.objects.get(pk=hidden.pk)
        assert migrated.title == "迁移原文" and migrated.body == "原始正文"
        assert migrated.status == "published" and migrated.project_tag_id == 1
        assert Article.objects.get(pk=public.pk).seed_key == "same"
        assert migrated.seed_key != "same"
        assert migrated.cover_asset_id == asset.pk
        assert migrated.cover_asset.project_tag_id == 1
        assert migrated.cover_asset.path == asset.path
        assert Project.objects.get(pk=1).name == "公开"
    finally:
        MigrationExecutor(connection).migrate(latest)
