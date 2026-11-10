import io
import json
import random
import threading
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from PIL import Image
import pytest

from apps.catalog.models import (
    DictionaryItem,
    MapComposition,
    MapCompositionVersion,
    ResultArtifact,
    WorkspaceScene,
)
from apps.catalog.thumbnails import (
    PLACEHOLDER_WEBP,
    THUMBNAIL_MAX_BYTES,
    encode_thumbnail,
    generate_thumbnail,
    source_for,
    thumbnail_response,
)
from apps.content.models import Article
from apps.content.views import serialize, store_asset
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import Project, ProjectMembership

pytestmark = pytest.mark.django_db


@pytest.fixture
def storage(settings, tmp_path):
    settings.PROJECT_CONFIG = replace(
        settings.PROJECT_CONFIG,
        app_data=tmp_path / "app",
        research_data_root=tmp_path / "research",
    )
    settings.PROJECT_CONFIG.app_data.mkdir(parents=True)
    return settings.PROJECT_CONFIG.app_data


@pytest.fixture
def owner():
    user = get_user_model().objects.create_user("card-owner", password="test-pass")
    user.user_permissions.set(
        Permission.objects.filter(
            codename__in=[
                "view_resultartifact",
                "add_resultartifact",
                "publish_resultartifact",
                "view_mapcomposition",
                "export_mapcomposition",
                "add_mapcomposition",
            ]
        )
    )
    return user


def image_bytes(format="PNG"):
    output = io.BytesIO()
    Image.new("RGB", (2000, 1000), (20, 120, 80)).save(output, format=format)
    return output.getvalue()


def result(storage, owner, suffix="png"):
    path = storage / f"exports/card.{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        image_bytes("PDF" if suffix == "pdf" else "PNG")
        if suffix != "csv"
        else b"value\n1\n"
    )
    return ResultArtifact.objects.create(
        category=DictionaryItem.objects.get(code="spatial"),
        owner=owner,
        name="卡片成果",
        file_name=path.name,
        file_path=f"exports/{path.name}",
        size_bytes=path.stat().st_size,
        status="published",
    )


def read_body(response):
    body = (
        b"".join(response.streaming_content) if response.streaming else response.content
    )
    response.close()
    return body


@pytest.mark.parametrize("suffix", ["png", "pdf", "csv"])
def test_result_model_write_prepares_small_webp(storage, owner, suffix):
    artifact = result(storage, owner, suffix)
    target = source_for(artifact).target
    assert target.is_file()
    assert target.stat().st_size <= THUMBNAIL_MAX_BYTES
    with Image.open(target) as image:
        assert max(image.size) <= 640
        assert image.format == "WEBP"
    if suffix == "csv":
        assert target.read_bytes() == PLACEHOLDER_WEBP


def test_failed_write_keeps_source_and_read_only_returns_placeholder(storage, owner):
    with patch(
        "apps.catalog.thumbnails.encode_thumbnail", side_effect=OSError("编码失败")
    ):
        artifact = result(storage, owner)
    source = source_for(artifact)
    assert source.path.is_file()
    assert not source.target.exists()
    with patch("apps.catalog.thumbnails.enqueue_thumbnail") as enqueue:
        assert read_body(thumbnail_response(source)) == PLACEHOLDER_WEBP
        enqueue.assert_called_once_with(source)


def test_high_entropy_image_obeys_byte_budget(storage):
    path = storage / "noise.png"
    Image.frombytes(
        "RGB", (1024, 768), random.Random(0).randbytes(1024 * 768 * 3)
    ).save(path)
    encoded = encode_thumbnail(path)
    assert len(encoded) <= THUMBNAIL_MAX_BYTES
    with Image.open(io.BytesIO(encoded)) as image:
        assert max(image.size) <= 640


def test_article_upload_create_and_cover_replacement_prepare_thumbnail(storage, owner):
    article = Article.objects.create(
        owner=owner, kind="news", title="动态", category="进展", status="published"
    )
    first = store_asset(article, "cover.png", image_bytes())
    assert source_for(first).target.is_file()
    article.cover_asset = first
    source_for(first).target.unlink()
    article.save()
    assert source_for(first).target.is_file()
    old_url = serialize(article)["thumbnailUrl"]
    second = store_asset(article, "new.jpg", image_bytes("JPEG"))
    article.cover_asset = second
    article.save()
    assert serialize(article)["thumbnailUrl"] != old_url
    assert source_for(second).target.is_file()


def test_composition_version_write_prepares_thumbnail(storage, owner, client):
    project = WorkspaceScene.objects.create(owner=owner, name="工程", kind="project")
    composition = MapComposition.objects.create(
        owner=owner, project=project, name="地图成果"
    )
    path = storage / "preview.png"
    path.write_bytes(image_bytes())
    version = MapCompositionVersion.objects.create(
        composition=composition,
        version_number=1,
        format="png",
        width_px=2000,
        height_px=1000,
        preview_path="preview.png",
        artifact_path="preview.png",
    )
    assert source_for(version).target.is_file()
    client.force_login(owner)
    with (
        patch("PIL.Image.open", side_effect=AssertionError("读取不得解码")),
        patch(
            "apps.core.map_thumbnail.thumbnail_tile",
            side_effect=AssertionError("卡片不得请求地图瓦片"),
        ),
    ):
        response = client.get(
            f"/api/catalog/map-compositions/{composition.pk}/versions/1/file/?variant=thumbnail&v={source_for(version).version}"
        )
        assert response.status_code == 200
        assert read_body(response)
    viewer = get_user_model().objects.create_user(
        "map-card-viewer", password="test-pass"
    )
    viewer.user_permissions.add(Permission.objects.get(codename="view_mapcomposition"))
    client.force_login(viewer)
    assert (
        client.get(
            f"/api/catalog/map-compositions/{composition.pk}/versions/1/file/?variant=thumbnail"
        ).status_code
        == 404
    )


@pytest.mark.efficiency
def test_reads_open_one_thumbnail_and_never_open_original_or_decode(
    storage, owner, client
):
    artifact = result(storage, owner)
    source = source_for(artifact)
    client.force_login(owner)
    original_open = Path.open
    opened = []

    def track_open(path, *args, **kwargs):
        opened.append(path)
        return original_open(path, *args, **kwargs)

    with (
        patch("PIL.Image.open", side_effect=AssertionError("读取不得解码")),
        patch(
            "apps.catalog.thumbnails.subprocess.run",
            side_effect=AssertionError("读取不得渲染"),
        ),
        patch.object(Path, "open", track_open),
    ):
        for _ in range(2):
            response = client.get(
                f"/api/catalog/results/{artifact.pk}/file/?variant=thumbnail&v={source.version}"
            )
            assert response.status_code == 200
            assert read_body(response)
    assert opened.count(source.target) == 2
    assert source.path not in opened


@pytest.mark.efficiency
def test_missing_read_returns_tiny_placeholder_and_enqueues_without_decode(
    storage, owner
):
    artifact = result(storage, owner)
    source = source_for(artifact)
    source.target.unlink()
    with (
        patch("apps.catalog.thumbnails.enqueue_thumbnail") as enqueue,
        patch("PIL.Image.open", side_effect=AssertionError("读取不得解码")),
        patch(
            "apps.catalog.thumbnails.generate_thumbnail",
            side_effect=AssertionError("读取不得生成"),
        ),
    ):
        response = thumbnail_response(source)
        assert read_body(response) == PLACEHOLDER_WEBP
        assert response["Cache-Control"] == "private, no-store"
        enqueue.assert_called_once_with(source)
    assert generate_thumbnail(source)
    assert not generate_thumbnail(source)


def test_content_change_invalidates_address_and_old_version(storage, owner, client):
    artifact = result(storage, owner)
    old = source_for(artifact)
    artifact.file_path = "exports/replaced.png"
    (storage / artifact.file_path).write_bytes(image_bytes("JPEG"))
    artifact.save()
    current = source_for(artifact)
    assert current.version != old.version
    assert current.target.is_file()
    client.force_login(owner)
    assert (
        client.get(
            f"/api/catalog/results/{artifact.pk}/file/?variant=thumbnail&v={old.version}"
        ).status_code
        == 404
    )


def test_permission_project_revocation_and_unpublished_result(storage, owner, client):
    private = Project.objects.create(name="私有", code="card-private")
    membership = ProjectMembership.objects.create(project=private, user=owner)
    with project_scope(
        ProjectScope(ids=(private.pk,), selected=private.pk, user_id=owner.pk)
    ):
        artifact = result(storage, owner)
    url = f"/api/catalog/results/{artifact.pk}/file/?variant=thumbnail&projectTagId={private.pk}&v={source_for(artifact).version}"
    client.force_login(owner)
    with patch("PIL.Image.open", side_effect=AssertionError("读取不得解码")):
        response = client.get(url)
    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]
    read_body(response)
    membership.delete()
    assert client.get(url).status_code == 404
    viewer = get_user_model().objects.create_user("card-viewer", password="test-pass")
    viewer.user_permissions.add(Permission.objects.get(codename="view_resultartifact"))
    public = result(storage, owner)
    public.status = "draft"
    public.save()
    client.force_login(viewer)
    assert (
        client.get(
            f"/api/catalog/results/{public.pk}/file/?variant=thumbnail"
        ).status_code
        == 404
    )


def test_content_thumbnail_rechecks_publication_and_pending_owner(
    storage, owner, client
):
    article = Article.objects.create(
        owner=owner, kind="news", title="动态", category="进展", status="published"
    )
    asset = store_asset(article, "cover.png", image_bytes())
    url = f"/api/content/assets/{asset.pk}/?variant=thumbnail&v={source_for(asset).version}"
    response = client.get(url)
    assert response.status_code == 200
    etag = response["ETag"]
    assert "must-revalidate" in response["Cache-Control"]
    read_body(response)
    assert client.get(url, HTTP_IF_NONE_MATCH=etag).status_code == 304
    article.status = "archived"
    article.save()
    assert client.get(url, HTTP_IF_NONE_MATCH=etag).status_code == 404
    article.status = "published"
    article.save()
    pending = store_asset(
        article, "pending.jpg", image_bytes("JPEG"), pending_owner=owner
    )
    pending_url = f"/api/content/assets/{pending.pk}/?variant=thumbnail"
    assert client.get(pending_url).status_code == 404
    owner.is_superuser = True
    owner.save()
    client.force_login(owner)
    response = client.get(pending_url)
    assert response.status_code == 200
    read_body(response)
    other = get_user_model().objects.create_superuser(
        "other-card-editor", password="test-pass"
    )
    client.force_login(other)
    assert client.get(pending_url).status_code == 404


def test_cover_conditional_update_rebuilds_missing_thumbnail(storage, owner, client):
    owner.is_superuser = True
    owner.save()
    article = Article.objects.create(
        owner=owner, kind="news", title="动态", category="进展"
    )
    asset = store_asset(article, "cover.png", image_bytes())
    source_for(asset).target.unlink()
    client.force_login(owner)
    response = client.post(
        f"/api/content/articles/{article.pk}/",
        data=json.dumps({"revision": article.revision, "coverAssetId": asset.pk}),
        content_type="application/json",
    )
    assert response.status_code == 200
    assert source_for(asset).target.is_file()
    assert "variant=thumbnail" in response.json()["thumbnailUrl"]


@pytest.mark.efficiency
def test_background_repair_is_singleflight_and_returns_before_encoding(storage, owner):
    from apps.catalog import thumbnails

    artifact = result(storage, owner)
    source = source_for(artifact)
    source.target.unlink()
    entered = threading.Event()
    release = threading.Event()
    encode = thumbnails.encode_thumbnail

    def delayed_encode(path):
        entered.set()
        assert release.wait(5)
        return encode(path)

    try:
        with patch.object(
            thumbnails, "encode_thumbnail", side_effect=delayed_encode
        ) as mocked:
            response = thumbnail_response(source)
            assert read_body(response) == PLACEHOLDER_WEBP
            assert entered.wait(5)
            for _ in range(5):
                assert not thumbnails.enqueue_thumbnail(source)
            release.set()
            thumbnails._repair_queue.join()
            assert mocked.call_count == 1
    finally:
        release.set()
    assert source.target.is_file()


def test_backfill_all_projects_dry_run_idempotent_and_resume(storage, owner):
    first = result(storage, owner)
    second = result(storage, owner, "pdf")
    for artifact in (first, second):
        source_for(artifact).target.unlink()
    output = io.StringIO()
    call_command("backfill_card_thumbnails", dry_run=True, stdout=output)
    assert "'missing': 2" in output.getvalue()
    assert not source_for(first).target.exists()
    call_command(
        "backfill_card_thumbnails", kind="result", limit=1, stdout=io.StringIO()
    )
    assert source_for(first).target.exists()
    assert not source_for(second).target.exists()
    call_command(
        "backfill_card_thumbnails",
        kind="result",
        after_id=first.pk,
        stdout=io.StringIO(),
    )
    assert source_for(second).target.exists()
    with patch(
        "apps.catalog.thumbnails.encode_thumbnail",
        side_effect=AssertionError("重复执行不得重编码"),
    ):
        call_command("backfill_card_thumbnails", stdout=io.StringIO())


def test_backfill_failure_is_resumable_and_nonzero(storage, owner):
    artifact = result(storage, owner)
    source_for(artifact).target.unlink()
    source_for(artifact).path.unlink()
    with pytest.raises(CommandError, match="1 项生成失败"):
        call_command(
            "backfill_card_thumbnails", stdout=io.StringIO(), stderr=io.StringIO()
        )
    source_for(artifact).path.write_bytes(image_bytes())
    call_command("backfill_card_thumbnails", stdout=io.StringIO())
    assert source_for(artifact).target.exists()


def test_backfill_includes_private_projects_even_in_public_scope(storage, owner):
    private = Project.objects.create(name="私有回填", code="card-backfill-private")
    with project_scope(
        ProjectScope(ids=(private.pk,), selected=private.pk, user_id=owner.pk)
    ):
        artifact = result(storage, owner)
    source_for(artifact).target.unlink()
    with project_scope(ProjectScope(ids=(1,), selected=1, user_id=owner.pk)):
        call_command("backfill_card_thumbnails", stdout=io.StringIO())
    assert source_for(artifact).target.is_file()


def test_backfill_keyboard_interrupt_preserves_completed_items(storage, owner):
    first = result(storage, owner)
    second = result(storage, owner, "pdf")
    for artifact in (first, second):
        source_for(artifact).target.unlink()

    def interrupt_after_first(source):
        if source.key == source_for(second).key:
            raise KeyboardInterrupt
        return generate_thumbnail(source)

    output = io.StringIO()
    with patch(
        "apps.catalog.management.commands.backfill_card_thumbnails.generate_thumbnail",
        side_effect=interrupt_after_first,
    ):
        call_command("backfill_card_thumbnails", stdout=output)
    assert "已中断" in output.getvalue()
    assert source_for(first).target.is_file()
    assert not source_for(second).target.exists()
    call_command("backfill_card_thumbnails", stdout=io.StringIO())
    assert source_for(second).target.is_file()
