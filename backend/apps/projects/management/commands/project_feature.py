import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.service import log_operation
from apps.projects.context import is_superadmin
from apps.projects.features import UNSET, set_feature
from apps.projects.models import Project, ProjectFeature


class Command(BaseCommand):
    help = "注册项目功能，或设置单个项目/全局开关及项目内容配置（记录审计）"

    def add_arguments(self, parser):
        parser.add_argument("feature", help="功能标识，例如 ecology_monitor")
        parser.add_argument(
            "--actor", required=True, help="执行操作的现有超级管理员用户名"
        )
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument("--project", help="项目稳定编码")
        scope.add_argument("--all-projects", action="store_true", help="设置全局开关")
        scope.add_argument(
            "--register", action="store_true", help="注册默认关闭的新功能"
        )
        state = parser.add_mutually_exclusive_group()
        state.add_argument("--enable", action="store_true")
        state.add_argument("--disable", action="store_true")
        parser.add_argument(
            "--config", type=Path, help="项目内容配置 JSON 路径；null 清除配置"
        )

    @transaction.atomic
    def handle(self, *args, **options):
        user = (
            get_user_model()
            .objects.filter(username=options["actor"], is_active=True)
            .first()
        )
        if user is None or not is_superadmin(user):
            raise CommandError("actor 必须是启用的超级管理员")
        try:
            candidate = ProjectFeature(key=options["feature"])
            candidate._meta.get_field("key").clean(options["feature"], candidate)
            if options["register"]:
                if (
                    options["enable"]
                    or options["disable"]
                    or options["config"] is not None
                ):
                    raise CommandError("注册时不能修改开关或配置")
                feature, created = ProjectFeature.objects.get_or_create(
                    key=options["feature"]
                )
                if created:
                    log_operation(
                        user,
                        "项目功能",
                        "注册功能",
                        "success",
                        feature.key,
                        target_type="project_feature",
                        target_id=feature.pk,
                        target_code=feature.key,
                    )
                self.stdout.write(self.style.SUCCESS(f"功能已注册：{feature.key}"))
                return
            feature = ProjectFeature.objects.get(key=options["feature"])
            project = (
                Project.objects.get(code=options["project"])
                if options["project"]
                else None
            )
            enabled = (
                options["enable"] if options["enable"] or options["disable"] else UNSET
            )
            config = UNSET
            if options["config"] is not None:
                config = json.loads(options["config"].read_text(encoding="utf-8"))
            set_feature(user, feature, project=project, enabled=enabled, config=config)
        except (Project.DoesNotExist, ProjectFeature.DoesNotExist) as error:
            raise CommandError("项目或功能不存在；新功能请先使用 --register") from error
        except (ValidationError, PermissionDenied, OSError, ValueError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS("项目功能设置已保存并写入审计日志"))
