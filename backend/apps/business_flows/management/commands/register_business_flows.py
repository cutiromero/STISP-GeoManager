"""Publish built-in flows explicitly; GET requests never populate the catalog."""

import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.business_flows.builtins import builtin_flows
from apps.business_flows.catalog import publish_version, register_flow, require_manager
from apps.business_flows.definitions import definition_hash, normalize_definition
from apps.business_flows.models import BusinessFlowDefinition
from apps.business_flows.scopes import (
    GEOLOGY_FLOW_CODE,
    PUBLIC_PROJECT_ID,
    require_registration_project,
)
from apps.projects.access import can_access_project
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import Project


class Command(BaseCommand):
    help = "Register immutable built-in business flows in a selected project"

    def add_arguments(self, parser):
        parser.add_argument("--project-id", type=int, required=True)
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--publish-updates",
            action="store_true",
            help="Explicitly publish code defaults over an existing custom version",
        )

    def handle(self, *args, **options):
        user = (
            get_user_model()
            .objects.filter(pk=options["user_id"], is_active=True)
            .first()
        )
        project = Project.objects.filter(
            pk=options["project_id"], is_active=True
        ).first()
        if user is None or project is None or not can_access_project(user, project.pk):
            raise CommandError("项目或登记账号不存在、已停用或无权访问")
        results = []
        with (
            project_scope(ProjectScope((project.pk,), project.pk, user.pk)),
            transaction.atomic(),
        ):
            require_manager(user)
            for value in builtin_flows():
                try:
                    require_registration_project(value["code"], project.pk)
                except ValidationError:
                    continue
                normalized = normalize_definition(value["definition"])
                flow = (
                    BusinessFlowDefinition.objects.select_related("current_version")
                    .filter(code=value["code"])
                    .first()
                )
                if (
                    project.pk != PUBLIC_PROJECT_ID
                    and value["code"] != GEOLOGY_FLOW_CODE
                    and flow is None
                ):
                    continue
                changed = (
                    not flow
                    or not flow.current_version
                    or flow.current_version.definition_hash
                    != definition_hash(normalized)
                )
                should_publish = changed and (
                    not flow or not flow.current_version or options["publish_updates"]
                )
                if options["dry_run"]:
                    results.append(
                        {"code": value["code"], "wouldPublish": should_publish}
                    )
                    continue
                if flow is None:
                    flow, version = register_flow(user, value)
                elif should_publish:
                    flow, version = publish_version(user, flow, normalized)
                else:
                    version = flow.current_version
                results.append(
                    {
                        "id": flow.pk,
                        "code": flow.code,
                        "version": version.version,
                        "published": should_publish,
                    }
                )
        self.stdout.write(
            json.dumps(
                {
                    "projectId": project.pk,
                    "dryRun": options["dry_run"],
                    "items": results,
                },
                ensure_ascii=False,
            )
        )
