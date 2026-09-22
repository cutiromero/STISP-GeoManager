from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.content.models import Article
from apps.content.seed_knowledge import ARTICLES
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
                title="学术交流｜China Partners Academic Forum 2026 第三场研讨会",
                summary="围绕 AI 时代的生态系统与环境研究，会议材料展示了从地球观测到可持续发展目标的综合评估议题。",
                event_date=date(2026, 9, 11),
                source="用户提供：2026S3海报.pdf、From Earth Observation to SDGs.pdf、报告封面及会议照片。会议名称与日期据海报，报告题名及署名据报告封面。",
                body="## 会议主题\n\n根据会议海报，China Partners Academic Forum 2026 的 Seminar 3 于 2026 年 9 月 11 日举行，主题为 Ecosystem and Environmental Research in the AI Era（AI 时代的生态系统与环境研究）。议程中列有 WANG Haoyu 与 Maolin Li。\n\n## 报告内容\n\n提供的报告题为 From Earth Observation to SDGs: Integrated Assessment of Forest Carbon, Wildfire, and Desertification across the East Asian Drylands，围绕东亚干旱区森林碳、野火与荒漠化的综合评估展开，将地球观测与可持续发展目标联系起来。\n\n报告封面标注主讲人为 Maolin Li，指导教师为 Haoyu Wang、Zhanfeng Shen 和 Qiang Yu。具体研究内容可查看下方原始报告。\n\n## 会议资料\n\n本条动态依据提供的会议海报、报告与照片整理。图集展示材料中的会议现场，不对照片人物身份作额外推断。活动日期与本平台的内容发布日期分别记录。",
                status="draft",
            )
            cover = news / "From Earth Observation to SDGs_01.png"
            article.cover_asset = store_asset(
                article,
                "报告封面.jpg",
                compact_image(cover.read_bytes()),
                "报告封面，保留原报告题名与署名。",
            )
            for photo in sorted(news.glob("*.jpg")) + sorted(news.glob("*.JPG")):
                store_asset(
                    article,
                    photo.stem + ".jpg",
                    compact_image(photo.read_bytes()),
                    "会议现场（用户提供素材）",
                )
            for pdf in sorted(news.glob("*.pdf")):
                store_asset(
                    article, pdf.name, pdf.read_bytes(), "用户提供的原始会议资料"
                )
            article.status = "published"
            article.published_at = timezone.now()
            article.save()
            created += 1
        self.stdout.write(self.style.SUCCESS(f"新增 {created} 条内容，已有内容保留。"))
