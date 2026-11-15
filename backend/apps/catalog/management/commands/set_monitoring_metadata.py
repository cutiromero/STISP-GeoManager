"""Maintain registered usage and observation time without changing raw data."""

import json
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from apps.catalog.monitoring_metadata import readable_resource, update_metadata
from apps.projects.models import Project
from apps.projects.context import ProjectScope, project_scope

# CONFIGURATION
DEFAULT_ACTOR = "admin"


class Command(BaseCommand):
    help = "维护监测资料用途、真实时相及原生时间索引"

    def add_arguments(self, parser):
        parser.add_argument("--project", required=True)
        parser.add_argument("--actor", default=DEFAULT_ACTOR)
        parser.add_argument("--resource", required=True, type=int)
        parser.add_argument("--metadata-json", required=True)

    def handle(self, *args, **options):
        project = Project.objects.get(code=options["project"], is_active=True)
        actor = get_user_model().objects.get(username=options["actor"], is_active=True)
        try:
            with project_scope(ProjectScope((project.pk,), project.pk, actor.pk)):
                resource = readable_resource(actor, options["resource"])
                if resource is None:
                    raise CommandError("资料不存在或无权访问")
                value = update_metadata(
                    actor, resource, json.loads(options["metadata_json"])
                )
            self.stdout.write(json.dumps(value, ensure_ascii=False))
        except (PermissionDenied, ValidationError, ValueError) as error:
            raise CommandError(str(error)) from error
