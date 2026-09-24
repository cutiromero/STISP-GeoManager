from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.content.models import Article
from apps.content.seed_knowledge import ARTICLES
from apps.content.seed_news import (
    NEWS_BODY,
    NEWS_SUMMARY,
    NEWS_TITLE,
    news_asset_caption,
)
from apps.content.seed_materials import compact_image, slide_illustration
from apps.content.views import store_asset


class Command(BaseCommand):
    help = "从用户提供的素材初始化公开项目科普与会议新闻；已有条目不会被覆盖。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source", required=True, help="包含课件目录和示例新闻目录的根目录"
        )

    def handle(self, *args, **options):
        root = Path(options["source"])
        course = root / "沈老师时空智能课程课件"
        news = root / "示例新闻-学术会议"
        if not course.is_dir() or not news.is_dir():
            raise CommandError("素材目录不完整")
        created = 0
        for key, category, title, lecture, page, summary, body, links in ARTICLES:
            seed_key = f"knowledge-{key}"
            if Article.objects.filter(project_tag_id=1, seed_key=seed_key).exists():
                continue
            content, source = slide_illustration(course, lecture, page)
            article = Article.objects.create(
                project_tag_id=1,
                seed_key=seed_key,
                kind="knowledge",
                title=title,
                category=category,
                summary=summary,
                body=body,
                source=source,
                links=[{"title": name, "url": url} for name, url in links],
                status="draft",
            )
            asset = store_asset(
                article,
                f"{key}.jpg",
                content,
                f"{title}：课件素材第 {lecture} 讲 P{page}，原图示意。",
            )
            article.cover_asset = asset
            article.status = "published"
            article.published_at = timezone.now()
            article.save()
            created += 1
        if not Article.objects.filter(
            project_tag_id=1, seed_key="news-china-partners-2026-s3"
        ).exists():
            article = Article.objects.create(
                project_tag_id=1,
                seed_key="news-china-partners-2026-s3",
                kind="news",
                category="学术会议",
                title=NEWS_TITLE,
                summary=NEWS_SUMMARY,
                event_date=date(2026, 9, 11),
                source="",
                body=NEWS_BODY,
                status="draft",
            )
            cover = news / "From Earth Observation to SDGs_01.png"
            article.cover_asset = store_asset(
                article,
                "报告封面.jpg",
                compact_image(cover.read_bytes()),
                news_asset_caption("报告封面.jpg", "image/jpeg"),
            )
            for photo in sorted(news.glob("*.jpg")) + sorted(news.glob("*.JPG")):
                store_asset(
                    article,
                    photo.stem + ".jpg",
                    compact_image(photo.read_bytes()),
                    news_asset_caption(photo.name, "image/jpeg"),
                )
            for pdf in sorted(news.glob("*.pdf")):
                store_asset(
                    article,
                    news_asset_caption(pdf.name, "application/pdf") + ".pdf",
                    pdf.read_bytes(),
                    news_asset_caption(pdf.name, "application/pdf"),
                )
            article.status = "published"
            article.published_at = timezone.now()
            article.save()
            created += 1
        self.stdout.write(self.style.SUCCESS(f"新增 {created} 条内容，已有内容保留。"))
