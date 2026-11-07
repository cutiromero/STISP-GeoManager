from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import DataResource
from apps.catalog.vector_tiles import prepare_vector_tiles
from apps.projects.context import ProjectScope, project_scope


class Command(BaseCommand):
    help = "从原始矢量只读快照预生成私有显示瓦片，不修改业务数据"

    def add_arguments(self, parser):
        parser.add_argument("--project-id", type=int, required=True)
        parser.add_argument("--resource-id", type=int, action="append", required=True)

    def handle(self, *args, **options):
        project = options["project_id"]
        if project <= 0:
            raise CommandError("项目ID不合法")
        with project_scope(
            ProjectScope(ids=(project,), selected=project, superadmin=True)
        ):
            for resource_id in options["resource_id"]:
                resource = DataResource.objects.filter(
                    pk=resource_id, status="active"
                ).first()
                if resource is None:
                    raise CommandError(f"当前项目没有启用资源{resource_id}")
                try:
                    preview = prepare_vector_tiles(resource, self.stdout.write)
                except (ValueError, OSError) as exc:
                    raise CommandError(str(exc)) from exc
                self.stdout.write(
                    f"READY {resource_id} {preview['revision']} {preview['featureCount']}"
                )
