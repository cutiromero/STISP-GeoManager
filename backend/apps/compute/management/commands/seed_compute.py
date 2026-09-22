"""Register first-party examples as drafts. Publication always needs a real trial."""

import io
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import UploadedFile
from django.core.management.base import BaseCommand, CommandError
from apps.compute.models import AlgorithmCategory, AlgorithmResource
from apps.compute.templates import build_package
from apps.compute.views import store_version
from apps.projects.context import ProjectScope, project_scope, is_superadmin


class Command(BaseCommand):
    help = "Register compute example packages as public drafts, never auto-publish"

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
            for index, name, category in [
                (1, "栅格线性变换", "栅格处理"),
                (2, "矢量缓冲区", "矢量分析"),
                (3, "表格分组汇总", "表格计算"),
            ]:
                data, identifier = build_package(index)
                AlgorithmCategory.objects.get_or_create(name=category)
                algorithm, _ = AlgorithmResource.objects.get_or_create(
                    identifier=identifier,
                    defaults={
                        "name": name,
                        "category": category,
                        "description": "平台提供的算法接入示例，须在隔离环境试运行后发布。",
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
        self.stdout.write(
            "已登记3个示例算法草稿；第4个模板可通过后台上传验证扩展能力。"
        )
