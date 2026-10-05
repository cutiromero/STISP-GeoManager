"""Precision and preservation checks for the two public science caption edits."""

from importlib import import_module
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.db import connection

from apps.content.models import Article, Asset


pytestmark = pytest.mark.django_db
migration = import_module(
    "apps.content.migrations.0007_trim_science_caption_provenance"
)


def make_article(seed, **overrides):
    return Article.objects.create(
        seed_key=seed,
        project_tag_id=1,
        kind="knowledge",
        title="原有标题",
        category="科普",
        summary="人工摘要",
        body="人工维护的正文",
        source="内部素材记录，保留原样",
        links=[{"title": "真实阅读", "url": "https://example.org"}],
        status=overrides.pop("status", "published"),
        revision=4,
        **overrides,
    )


def make_asset(article, checksum, caption):
    return Asset.objects.create(
        article=article,
        project_tag_id=1,
        name="原图.png",
        path="unchanged/original.png",
        mime_type="image/png",
        checksum=checksum,
        size_bytes=200,
        caption=caption,
    )


def run_migration():
    migration.trim_caption_provenance(apps, SimpleNamespace(connection=connection))


def test_exact_caption_suffixes_change_without_replacing_manual_text_or_sources():
    changed_ids, changed_articles = [], []
    for seed, checksum, page in migration.TARGETS:
        article = make_article(seed)
        prefix = f"人工完善的图像解释：第{page}张样例仍保留。"
        # Both original spacing and compact punctuation are accepted.
        suffix = (
            f"图源：课件第 8 讲，第 {page} 页。"
            if page == 21
            else f"图源：课件第8讲，第{page}页。"
        )
        asset = make_asset(article, checksum, prefix + suffix)
        changed_ids.append(asset.id)
        changed_articles.append(article.id)
        make_asset(
            article, "f" * 64, prefix + suffix
        )  # replacement image remains intact
        make_asset(article, checksum, "额外说明。图源：课件第 8 讲，第 99 页。")
        make_asset(article, checksum, prefix + suffix + "用户补充的结尾")
        make_asset(article, checksum, suffix)  # never erase a whole caption
    manual = make_article("manual-caption")
    make_asset(
        manual, migration.TARGETS[0][1], "自建文章解释。图源：课件第8讲，第21页。"
    )
    before_articles = {item["id"]: item for item in Article.objects.values()}
    before_assets = {item["id"]: item for item in Asset.objects.values()}
    run_migration()
    for after in Asset.objects.values():
        before = before_assets[after["id"]]
        if after["id"] in changed_ids:
            assert after["caption"] == before["caption"].split("图源：")[0]
            assert {k: v for k, v in after.items() if k != "caption"} == {
                k: v for k, v in before.items() if k != "caption"
            }
        else:
            assert after == before
    for after in Article.objects.values():
        before = before_articles[after["id"]]
        if after["id"] in changed_articles:
            assert after["revision"] == before["revision"] + 1
            assert {
                k: v for k, v in after.items() if k not in {"revision", "updated_at"}
            } == {
                k: v for k, v in before.items() if k not in {"revision", "updated_at"}
            }
        else:
            assert after == before
    stable = (list(Article.objects.values()), list(Asset.objects.values()))
    run_migration()
    assert (list(Article.objects.values()), list(Asset.objects.values())) == stable


@pytest.mark.parametrize("status", ["archived", "draft"])
def test_unpublished_history_is_unchanged(status):
    seed, checksum, _ = migration.TARGETS[0]
    article = make_article(seed, status=status)
    make_asset(article, checksum, "历史图注。图源：课件第8讲，第21页。")
    before = (list(Article.objects.values()), list(Asset.objects.values()))
    run_migration()
    assert (list(Article.objects.values()), list(Asset.objects.values())) == before
