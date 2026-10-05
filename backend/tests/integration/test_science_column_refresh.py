import hashlib
import io
import json

import pytest
from PIL import Image
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.content.management.commands import refresh_science_column as refresh
from apps.content.models import Article, Asset
from apps.content.science_document import load_science_manifest
from apps.content.seed_knowledge import ARTICLES as LEGACY_ARTICLES

pytestmark = pytest.mark.django_db


@pytest.fixture
def science_assets(tmp_path, monkeypatch):
    manifest = load_science_manifest()
    folder = tmp_path / "input"
    folder.mkdir()
    output = tmp_path / "stored"
    data = io.BytesIO()
    Image.new("RGB", (24, 24), "blue").save(data, "PNG")
    for item in manifest["articles"]:
        image = item["images"][0]
        image["name"] = f"science-{item['number']:02d}.png"
        image["sha256"] = hashlib.sha256(data.getvalue()).hexdigest()
        (folder / image["name"]).write_bytes(data.getvalue())
    monkeypatch.setattr(refresh, "load_science_manifest", lambda: manifest)
    monkeypatch.setattr(refresh, "app_path", lambda path: output / path)
    monkeypatch.setattr("apps.content.views.app_path", lambda path: output / path)
    return folder, output, manifest


def run_refresh(folder, **kwargs):
    result = io.StringIO()
    call_command("refresh_science_column", assets=str(folder), stdout=result, **kwargs)
    return json.loads(result.getvalue())


def test_refresh_retains_legacy_news_and_manual_content_and_is_idempotent(
    science_assets,
):
    folder, output, manifest = science_assets
    for item in LEGACY_ARTICLES:
        Article.objects.create(
            seed_key=f"knowledge-{item[0]}",
            kind="knowledge",
            title=item[2],
            category=item[1],
            body="保留的旧正文",
            status="published",
        )
    manual = Article.objects.create(
        kind="knowledge", title="人工文章", category="自定义", status="published"
    )
    news = Article.objects.create(
        kind="news",
        seed_key="news-custom",
        title="团队动态",
        category="新闻",
        status="published",
    )
    protected = list(Article.objects.filter(pk__in=[manual.pk, news.pk]).values())
    before = list(Article.objects.values())
    preview = run_refresh(folder, dry_run=True)
    assert preview["legacyToArchive"] == 12
    assert preview["articles"] == 8
    assert list(Article.objects.values()) == before
    assert not output.exists()

    assert run_refresh(folder) == {
        "created": 8,
        "updated": 0,
        "unchanged": 0,
        "archived": 12,
        "images": 8,
    }
    current = Article.objects.filter(seed_key__startswith="science-20260929-")
    assert [article.title for article in current] == [
        item["title"] for item in manifest["articles"]
    ]
    assert Article.objects.filter(status="archived", body="保留的旧正文").count() == 12
    assert (
        list(Article.objects.filter(pk__in=[manual.pk, news.pk]).values()) == protected
    )
    for article in current:
        item = next(
            item for item in manifest["articles"] if item["seedKey"] == article.seed_key
        )
        assert article.body == "\n\n".join(item["paragraphs"])
        assert article.links == item["links"]
        assert article.cover_asset.caption == item["images"][0]["caption"]
        if item["images"][0].get("source"):
            assert item["images"][0]["source"] in article.source
        assert (output / article.cover_asset.path).is_file()
    stable = list(current.values())
    assert run_refresh(folder) == {
        "created": 0,
        "updated": 0,
        "unchanged": 8,
        "archived": 0,
        "images": 8,
    }
    assert list(current.values()) == stable
    assert Asset.objects.count() == 8


def test_media_integrity_failure_keeps_database_unchanged(science_assets):
    folder, _, _ = science_assets
    existing = Article.objects.create(
        kind="knowledge",
        seed_key="knowledge-resolution",
        title="旧文章",
        category="遥感",
        status="published",
    )
    (folder / "science-08.png").write_bytes(b"different-image")
    with pytest.raises(CommandError, match="与原始文档不一致"):
        run_refresh(folder)
    existing.refresh_from_db()
    assert existing.status == "published"
    assert Article.objects.count() == 1
    assert Asset.objects.count() == 0


def test_mid_refresh_failure_rolls_back_database_and_new_media(
    science_assets, monkeypatch
):
    folder, output, _ = science_assets
    real_store = refresh.store_asset
    calls = 0

    def fail_later(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise ValueError("simulated media failure")
        return real_store(*args, **kwargs)

    monkeypatch.setattr(refresh, "store_asset", fail_later)
    with pytest.raises(ValueError, match="simulated"):
        run_refresh(folder)
    assert Article.objects.count() == 0
    assert Asset.objects.count() == 0
    assert not [path for path in output.rglob("*") if path.is_file()]
