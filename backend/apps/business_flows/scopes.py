"""Shared public definitions and project-owned catalogs; runs stay project-local."""

from django.core.exceptions import ValidationError
from django.db.models import Q

from apps.compute.project_tools import GEOLOGY_PROJECT_CODES
from apps.projects.context import selected_project_id
from apps.projects.models import Project
from .models import BusinessFlowDefinition

# Public registrations are reusable templates, following the algorithm catalog.
PUBLIC_PROJECT_ID = 1
GEOLOGY_FLOW_CODE = "geology-logic-reasoning"


def available_flows(project_id=None):
    project_id = selected_project_id() if project_id is None else project_id
    return BusinessFlowDefinition._base_manager.filter(
        project_tag_id__in={PUBLIC_PROJECT_ID, project_id},
        project_tag__is_active=True,
    ).filter(
        ~Q(code=GEOLOGY_FLOW_CODE) | Q(project_tag__code__in=GEOLOGY_PROJECT_CODES)
    )


def catalog_flows(*, manage=False):
    project_id = selected_project_id()
    query = available_flows(project_id)
    query = query.filter(
        Q(is_active=True) | Q(project_tag_id=project_id)
        if manage
        else Q(is_active=True)
    )
    if project_id != PUBLIC_PROJECT_ID:
        # A local customization takes precedence over the shared registration.
        local_codes = query.filter(project_tag_id=project_id).values("code")
        query = query.exclude(project_tag_id=PUBLIC_PROJECT_ID, code__in=local_codes)
    return query


def require_registration_project(code, project_id):
    if (
        code == GEOLOGY_FLOW_CODE
        and not Project.objects.filter(
            pk=project_id, code__in=GEOLOGY_PROJECT_CODES
        ).exists()
    ):
        raise ValidationError("逻辑推理业务流须登记在核地院逻辑推理项目")
