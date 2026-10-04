"""Register the topology repair operator as a draft, preserving manual edits."""

import io

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import UploadedFile
from django.core.management.base import BaseCommand, CommandError

from apps.compute.models import AlgorithmCategory, AlgorithmResource
from apps.compute.templates import build_package
from apps.compute.views import store_version
from apps.projects.context import ProjectScope, is_superadmin, project_scope


class Command(BaseCommand):
    help = "登记地质图面几何修复算法草稿；真实试运行通过后由管理员发布"

    def handle(self, *args, **options):
        user = next(
            (
                user
                for user in get_user_model()
                .objects.filter(is_active=True)
                .order_by("pk")
                if is_superadmin(user)
            ),
            None,
        )
        if user is None:
            raise CommandError("请先初始化超级管理员")
        data, identifier = build_package(7)
        with project_scope(ProjectScope((1,), 1, user.id, True)):
            AlgorithmCategory.objects.get_or_create(
                name="矢量分析", defaults={"sort_order": 20}
            )
            algorithm, _ = AlgorithmResource.objects.get_or_create(
                identifier=identifier,
                defaults={
                    "name": "地质图面几何修复",
                    "description": "检查并修复面要素自相交和无效环，保留原始输入、完整修复候选及逐要素审核记录。",
                    "category": "矢量分析",
                    "author": "STISP",
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
            "已检查登记地质图面几何修复；新增版本为草稿，真实试运行核对后发布。"
        )
