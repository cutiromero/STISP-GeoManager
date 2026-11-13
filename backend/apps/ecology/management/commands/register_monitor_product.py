import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.ecology.monitoring import MAX_MANIFEST_BYTES, register_product
from apps.projects.access import can_access_project
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import Project


class Command(BaseCommand):
    help = "登记已经标准入库的遥感监测成果；相同清单幂等，原成果不覆盖"

    def add_arguments(self, parser):
        parser.add_argument("--manifest", type=Path, required=True)
        parser.add_argument("--project", required=True)
        parser.add_argument("--actor", required=True)

    def handle(self, *args, **options):
        user = (
            get_user_model()
            .objects.filter(username=options["actor"], is_active=True)
            .first()
        )
        project = Project.objects.filter(
            code=options["project"], is_active=True
        ).first()
        if user is None or project is None or not can_access_project(user, project.pk):
            raise CommandError("账号或项目不存在、未启用或无权访问")
        try:
            path = options["manifest"]
            if path.stat().st_size > MAX_MANIFEST_BYTES:
                raise ValidationError("清单超过64KiB")
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            with project_scope(ProjectScope((project.pk,), project.pk, user.pk)):
                product, created = register_product(user, value)
            self.stdout.write(
                json.dumps(
                    {
                        "id": product.pk,
                        "code": product.product_code,
                        "created": created,
                    },
                    ensure_ascii=False,
                )
            )
        except (OSError, ValueError, ValidationError, PermissionDenied) as error:
            raise CommandError(str(error)) from error
