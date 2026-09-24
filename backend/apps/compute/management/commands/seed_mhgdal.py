"""Register portable MHGDAL tools as drafts; trials remain mandatory."""

import io
from pathlib import Path
import runpy
import sys

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import UploadedFile
from django.core.management.base import BaseCommand, CommandError
from apps.compute.models import AlgorithmCategory, AlgorithmResource
from apps.compute.views import store_version
from apps.projects.context import ProjectScope, project_scope, is_superadmin


class Command(BaseCommand):
    help = "登记MHGDAL工具草稿及两个禁用占位接口，须真实试运行后发布"

    def handle(self, *args, **options):
        user = next(
            (
                u
                for u in get_user_model().objects.filter(is_active=True)
                if is_superadmin(u)
            ),
            None,
        )
        if user is None:
            raise CommandError("请先初始化超级管理员")
        directory = Path(settings.PROGRAM_ROOT) / "examples/compute/mhgdal"
        sys.path.insert(0, str(directory))
        try:
            package = runpy.run_path(str(directory / "build.py"))
            catalog = runpy.run_path(str(directory / "catalog.py"))
            with project_scope(ProjectScope((1,), 1, user.id, True)):
                for tool in catalog["TOOLS"]:
                    manifest = tool["manifest"]
                    AlgorithmCategory.objects.get_or_create(
                        name=tool["category"], defaults={"sort_order": 40}
                    )
                    algorithm, _ = AlgorithmResource.objects.get_or_create(
                        identifier=manifest["identifier"],
                        defaults=dict(
                            name=manifest["name"],
                            description=manifest["description"],
                            category=tool["category"],
                            author=manifest["author"],
                            created_by=user,
                        ),
                    )
                    if not algorithm.versions.filter(
                        version=manifest["version"]
                    ).exists():
                        data = package["build"](tool)
                        store_version(
                            algorithm,
                            UploadedFile(
                                io.BytesIO(data),
                                name=manifest["identifier"] + ".zip",
                                size=len(data),
                            ),
                        )
                for key, name, source in catalog["PLACEHOLDERS"]:
                    AlgorithmResource.objects.get_or_create(
                        identifier="mhgdal-" + key,
                        defaults=dict(
                            name=name,
                            description=source + "：原代码仅有接口，待补充实现。",
                            category="MHGDAL 栅格工具",
                            author="MHGDALBasicAlgorithms",
                            created_by=user,
                            enabled=False,
                        ),
                    )
        finally:
            sys.path.pop(0)
        self.stdout.write("已登记21个工具草稿，2个禁用占位；新版本须真实试运行后发布。")
