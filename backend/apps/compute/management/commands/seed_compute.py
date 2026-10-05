"""Register first-party examples as drafts. Publication always needs a real trial."""

import io
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import UploadedFile
from django.core.management.base import BaseCommand, CommandError
from apps.compute.models import AlgorithmCategory, AlgorithmResource
from apps.compute.templates import build_package
from apps.compute.views import store_version
from apps.projects.context import ProjectScope, project_scope, is_superadmin


NDVI_DESCRIPTION = (
    "选择同一幅多波段反射率影像的红光、近红外波段，"
    "按 (近红外−红光)/(近红外＋红光) 计算 NDVI，用于植被覆盖与长势的辅助分析。"
    "输出单波段 Float32 GeoTIFF，保留坐标系、分辨率及范围；"
    "无效像元与零分母标记为 NoData（−9999）。"
)


class Command(BaseCommand):
    help = "Register compute example packages as public drafts, never auto-publish"

    def add_arguments(self, parser):
        parser.add_argument("--only", nargs="+", type=int, choices=range(1, 7))

    def handle(self, *args, **options):
        user = next(
            (
                u
                for u in get_user_model().objects.filter(is_active=True)
                if is_superadmin(u)
            ),
            None,
        )
        if not user:
            raise CommandError("请先初始化超级管理员")
        with project_scope(ProjectScope((1,), 1, user.id, True)):
            count = 0
            for index, name, category in [
                (1, "栅格线性变换", "栅格处理"),
                (2, "矢量缓冲区", "矢量分析"),
                (3, "表格分组汇总", "表格计算"),
                (4, "NDVI示例", "栅格处理"),
                (5, "NDWI水体指数", "栅格处理"),
                (6, "矢量面积与周长", "矢量分析"),
            ]:
                if options.get("only") and index not in options["only"]:
                    continue
                data, identifier = build_package(index)
                AlgorithmCategory.objects.get_or_create(
                    name=category,
                    defaults={
                        "sort_order": {"栅格处理": 10, "矢量分析": 20, "表格计算": 30}[
                            category
                        ]
                    },
                )
                algorithm, _ = AlgorithmResource.objects.get_or_create(
                    identifier=identifier,
                    defaults={
                        "name": name,
                        "category": category,
                        "description": (
                            NDVI_DESCRIPTION
                            if identifier == "raster-ndvi"
                            else "平台提供的算法接入示例，须在隔离环境试运行后发布。"
                        ),
                        "author": "平台示例算法",
                        "created_by": user,
                    },
                )
                if not algorithm.versions.filter(version="1.0.0").exists():
                    store_version(
                        algorithm,
                        UploadedFile(
                            io.BytesIO(data), name=identifier + ".zip", size=len(data)
                        ),
                    )
                count += 1
        self.stdout.write(
            f"已检查登记{count}个算法；新增版本为草稿，试运行核对后发布。"
        )
