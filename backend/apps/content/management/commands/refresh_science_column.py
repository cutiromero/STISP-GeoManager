"""Publish the supplied eight-article column while retaining previous seeds."""

import hashlib
import io
import json
from datetime import timedelta
from pathlib import Path

from PIL import Image
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.content.models import Article, Asset
from apps.content.science_document import load_science_manifest
from apps.content.seed_knowledge import ARTICLES as LEGACY_ARTICLES
from apps.content.views import store_asset
from apps.core.storage import app_path
from apps.projects.context import ProjectScope, project_scope


def validated_media(folder: Path, manifest: dict) -> dict[str, bytes]:
    media = {}
    for article in manifest["articles"]:
        for image in article["images"]:
            name = image["name"]
            target = (folder / name).resolve()
            if target.parent != folder or not target.is_file():
                raise CommandError(f"缺少对应的科普插图：{name}")
            content = target.read_bytes()
            if hashlib.sha256(content).hexdigest() != image["sha256"]:
                raise CommandError(f"科普插图与原始文档不一致：{name}")
            if len(content) > 30 * 1024 * 1024:
                raise CommandError(f"科普插图超过 30 MiB：{name}")
            try:
                with Image.open(io.BytesIO(content)) as decoded:
                    decoded.verify()
            except (OSError, ValueError) as exc:
                raise CommandError(f"科普插图无效：{name}") from exc
            media[name] = content
    return media


class Command(BaseCommand):
    help = "用 2026-09-29 DOCX 的八篇科普刷新栏目；仅归档旧版种子，保留新闻和人工文章。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--assets", required=True, help="从原 DOCX 提取的 science-assets 目录"
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="校验素材并报告范围，不写入数据库"
        )

    def handle(self, *args, **options):
        manifest = load_science_manifest()
        folder = Path(options["assets"]).resolve()
        media = validated_media(folder, manifest)
        legacy_keys = [f"knowledge-{item[0]}" for item in LEGACY_ARTICLES]
        new_keys = [item["seedKey"] for item in manifest["articles"]]
        with project_scope(ProjectScope((1,), 1, superadmin=True)):
            legacy = Article.objects.filter(kind="knowledge", seed_key__in=legacy_keys)
            existing = Article.objects.filter(seed_key__in=new_keys)
            if existing.exclude(kind="knowledge").exists():
                raise CommandError("新版种子标识已被其他内容类型使用，请先核查")
            if options["dry_run"]:
                self.stdout.write(
                    json.dumps(
                        {
                            "dryRun": True,
                            "articles": len(new_keys),
                            "images": len(media),
                            "links": sum(len(a["links"]) for a in manifest["articles"]),
                            "legacyToArchive": legacy.exclude(
                                status="archived"
                            ).count(),
                            "existingNewArticles": existing.count(),
                        },
                        ensure_ascii=False,
                    )
                )
                return
            created_paths: list[Path] = []
            try:
                with transaction.atomic():
                    counts = {"created": 0, "updated": 0, "unchanged": 0}
                    publication_time = timezone.now()
                    for index, item in enumerate(manifest["articles"]):
                        article, created = Article.objects.get_or_create(
                            seed_key=item["seedKey"],
                            defaults={
                                "kind": "knowledge",
                                "title": item["title"],
                                "category": item["category"],
                            },
                        )
                        changed = created
                        cover = None
                        for image in item["images"]:
                            asset = Asset.objects.filter(
                                article=article,
                                checksum=image["sha256"],
                                expires_at__isnull=True,
                            ).first()
                            if asset is None:
                                asset = store_asset(
                                    article,
                                    image["name"],
                                    media[image["name"]],
                                    image["caption"],
                                )
                                created_paths.append(app_path(asset.path))
                                changed = True
                            elif asset.caption != image["caption"]:
                                asset.caption = image["caption"]
                                asset.save(update_fields=["caption"])
                                changed = True
                            cover = cover or asset
                        values = {
                            "kind": "knowledge",
                            "title": item["title"],
                            "category": item["category"],
                            "summary": item["summary"],
                            "body": "\n\n".join(item["paragraphs"]),
                            "source": "\n".join(
                                [
                                    f"《{manifest['sourceName']}》第 {item['number']} 篇；正文、配图与延伸阅读依照原文。"
                                ]
                                + [
                                    f"配图来源：{image['source']}"
                                    for image in item["images"]
                                    if image.get("source")
                                ]
                            ),
                            "links": item["links"],
                            "status": "published",
                            "cover_asset_id": cover.pk,
                        }
                        for key, value in values.items():
                            if getattr(article, key) != value:
                                setattr(article, key, value)
                                changed = True
                        if article.published_at is None:
                            # Keep the questions in document order with the existing API sort.
                            article.published_at = publication_time - timedelta(
                                seconds=index
                            )
                            changed = True
                        if changed:
                            article.revision += 0 if created else 1
                            article.full_clean()
                            article.save()
                        counts[
                            "created"
                            if created
                            else "updated"
                            if changed
                            else "unchanged"
                        ] += 1
                    archived = legacy.exclude(status="archived").update(
                        status="archived",
                        revision=F("revision") + 1,
                        updated_at=timezone.now(),
                    )
            except Exception:
                # Database rollback cannot remove newly created media files.
                for target in created_paths:
                    target.unlink(missing_ok=True)
                raise
        self.stdout.write(
            json.dumps(
                {**counts, "archived": archived, "images": len(media)},
                ensure_ascii=False,
            )
        )
