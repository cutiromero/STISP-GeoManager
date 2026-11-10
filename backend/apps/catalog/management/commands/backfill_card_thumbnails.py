"""按所有项目的内容主键顺序回填，已存在的版本直接跳过。"""

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import MapCompositionVersion, ResultArtifact
from apps.catalog.thumbnails import GENERATION_ERRORS, generate_thumbnail, source_for
from apps.content.models import Asset

CONFIGURATION = "卡片缩略图回填配置"
PROGRESS_EVERY = 25
SOURCES = (
    ("result", ResultArtifact),
    ("asset", Asset),
    ("composition", MapCompositionVersion),
)


class Command(BaseCommand):
    help = "为所有项目的成果、文章媒体、专题图/地图成果回填预生成缩略图"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
        parser.add_argument("--kind", choices=[name for name, _ in SOURCES])
        parser.add_argument("--after-id", type=int, default=0, help="从主键之后续跑")
        parser.add_argument(
            "--limit", type=int, default=0, help="本批最多处理数量；0 为全部"
        )

    def handle(self, *args, **options):
        if options["after_id"] < 0 or options["limit"] < 0:
            raise CommandError("after-id 与 limit 不能为负数")
        totals = dict(scanned=0, ready=0, missing=0, generated=0, failed=0)
        try:
            for name, model in SOURCES:
                if options["kind"] and options["kind"] != name:
                    continue
                query = model._base_manager.filter(pk__gt=options["after_id"]).order_by(
                    "pk"
                )
                if options["limit"]:
                    query = query[: options["limit"]]
                for instance in query.iterator(chunk_size=100):
                    totals["scanned"] += 1
                    source = source_for(instance)
                    if source.target.is_file():
                        totals["ready"] += 1
                    else:
                        totals["missing"] += 1
                        if not options["dry_run"]:
                            try:
                                totals["generated"] += int(generate_thumbnail(source))
                            except GENERATION_ERRORS as error:
                                totals["failed"] += 1
                                self.stderr.write(f"失败 {name}:{instance.pk} {error}")
                    if totals["scanned"] % PROGRESS_EVERY == 0:
                        self.stdout.write(
                            f"进度 {name} after-id={instance.pk} {totals}"
                        )
                self.stdout.write(f"完成来源 {name} {totals}")
        except KeyboardInterrupt:
            self.stdout.write(f"已中断；重新运行会跳过完成项。汇总 {totals}")
            return
        self.stdout.write(f"汇总 {totals}")
        if totals["failed"]:
            raise CommandError(f"{totals['failed']} 项生成失败；修复来源后可直接重跑")
