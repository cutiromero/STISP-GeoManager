"""Inventory and explicitly remove only unreferenced, proven compute copies."""

import json
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware

from apps.agent.models import AgentComputeFollowup, AgentWorkflowStep
from apps.catalog.resource_history_delete import history_snapshot
from apps.catalog.resource_management import delete_resource
from apps.catalog.resource_references import resource_reference_reasons
from apps.compute.models import ComputeImport, ComputeInput
from apps.ecology.models import RemoteSensingProduct
from apps.projects.context import ProjectScope, is_superadmin, project_scope

# A deletion may remove these automatically generated catalogue attachments only.
DERIVED_RELATIONS = {
    "computeimport_set",
    "map_layers",
    "raster_datasets",
    "source_datasets",
    "observation_metadata",
}
MAX_BATCH = 100


def protections(resource, record, before):
    task = record.output.task
    if (
        resource.pk != record.resource_id
        or record.status != "ready"
        or task.finished_at is None
        or task.finished_at >= before
        or task.status != "succeeded"
        or task.project_tag_id != resource.project_tag_id
        or not resource.is_compute_result
        or resource.source != f"compute-output:{record.storage_key}"
    ):
        return ["原始来源、项目或已结束旧计算的身份不能核实"]
    if ComputeInput.objects.filter(resource_id=resource.pk).exists():
        return ["下游计算或其历史仍引用此成果"]
    if (
        AgentWorkflowStep.objects.filter(compute_task_id=task.pk).exists()
        or AgentComputeFollowup.objects.filter(task_id=task.pk).exists()
    ):
        return ["此成果属已有工作流或智能体任务"]
    if any(
        resource.pk in (metadata.get("monitoring", {}).get("sourceResourceIds") or [])
        for metadata in RemoteSensingProduct._base_manager.filter(
            project_tag_id=resource.project_tag_id
        ).values_list("metadata", flat=True)
        if isinstance(metadata, dict)
    ):
        return ["正式登记依赖此成果"]
    for relation in resource._meta.related_objects:
        name = relation.get_accessor_name()
        if not name or name in DERIVED_RELATIONS:
            continue
        value = getattr(resource, name, None)
        if value is not None and (not hasattr(value, "exists") or value.exists()):
            return ["仍有关联目录、已登记成果或其他业务引用：" + name]
    _, facts = history_snapshot(resource)
    if facts["inputs"] or facts["workflows"] or len(facts["imports"]) != 1:
        return ["仍有任务历史引用或不唯一的入库来源"]
    return resource_reference_reasons(resource, allow_history=True)


class Command(BaseCommand):
    help = (
        "仅清理已确认旧计算副本；保留原件、正式产品、任务历史与关联成果。默认只读预检。"
    )

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)
        parser.add_argument("--before", required=True, help="带时区的完成时间上限")
        parser.add_argument("--resource-id", action="append", type=int, required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *, actor, before, resource_id, apply, **kwargs):
        user = get_user_model().objects.filter(username=actor, is_active=True).first()
        if user is None or not is_superadmin(user):
            raise CommandError("请指定有效的超级管理员账号")
        try:
            cutoff = parse_datetime(before)
        except ValueError as error:
            raise CommandError("请提供有效的带时区完成时间") from error
        ids = sorted(set(resource_id))
        if (
            cutoff is None
            or not is_aware(cutoff)
            or not 1 <= len(ids) <= MAX_BATCH
            or ids[0] < 1
        ):
            raise CommandError("须提供 1–100 个明确资源编号，以及带时区完成时间")
        records = ComputeImport.objects.filter(
            resource_id__in=ids, status="ready"
        ).select_related("resource", "output__task")
        by_resource = {}
        for record in records:
            by_resource.setdefault(record.resource_id, []).append(record)
        report = []
        for identity in ids:
            matches = by_resource.get(identity, [])
            if len(matches) != 1:
                report.append(
                    {
                        "resourceId": identity,
                        "status": "retained",
                        "reasons": ["无唯一计算入库记录"],
                    }
                )
                continue
            record = matches[0]
            project = record.resource.project_tag_id
            with project_scope(ProjectScope((project,), project, user.pk, True)):
                reasons = protections(record.resource, record, cutoff)
                if reasons or not apply:
                    report.append(
                        {
                            "resourceId": identity,
                            "status": "retained" if reasons else "eligible",
                            "reasons": reasons,
                        }
                    )
                    continue
                digest, _ = history_snapshot(record.resource)
                report.append(
                    delete_resource(
                        SimpleNamespace(user=user, META={}),
                        identity,
                        confirmed_snapshot=digest,
                        deletion_guard=lambda resource: (
                            not protections(resource, record, cutoff)
                        ),
                    )
                )
        self.stdout.write(json.dumps(report, ensure_ascii=False))
