"""Public provenance of a science task whose Agent may have prepared inputs."""

from django.core.exceptions import PermissionDenied, ValidationError

from apps.agent.models import AgentWorkflowStep
from apps.catalog.models import DataResource, task_resource_q
from apps.compute.models import ComputeImport

MAX_DEPTH = 6
MAX_INPUTS = 32


def source_resource_ids(task):
    """Follow only verified adaptation edges of the same owner's actual workflow.

    Preparation packets remain private to their task. The registry instead binds
    the real original inputs so every other viewer rechecks those same permissions.
    """
    workflow = None
    visited = set()

    def inputs(current, depth):
        nonlocal workflow
        if depth > MAX_DEPTH or current.pk in visited:
            raise ValidationError("监测成果的适配来源链过深或存在重复引用")
        visited.add(current.pk)
        ids = set(
            current.input_records.exclude(resource_id=None).values_list(
                "resource_id", flat=True
            )
        )
        if len(ids) > MAX_INPUTS:
            raise ValidationError("监测成果的资料来源数量超过登记范围")
        public = set(
            DataResource.objects.filter(
                pk__in=ids,
                project_tag_id=task.project_tag_id,
                status="active",
            )
            .exclude(task_resource_q())
            .values_list("pk", flat=True)
        )
        for identity in sorted(ids - public):
            if workflow is None:
                link = (
                    AgentWorkflowStep.objects.filter(
                        compute_task_id=task.pk,
                        kind="submit_operator",
                        workflow__owner_id=task.owner_id,
                        workflow__project_tag_id=task.project_tag_id,
                        workflow__workflow_type="business_flow",
                        workflow__status="succeeded",
                    )
                    .order_by("pk")
                    .first()
                )
                if link is None:
                    raise PermissionDenied("不能公开未经同一业务流证实的私有派生资料")
                workflow = link.workflow_id
            prefix = f"workflow-working:{workflow}:input-adapter:"
            record = (
                ComputeImport.objects.filter(
                    resource_id=identity,
                    resource__project_tag_id=task.project_tag_id,
                    resource__status="active",
                    resource__owner_only=True,
                    resource__source__startswith=prefix,
                    status="ready",
                    requested_by_id=task.owner_id,
                    request_source=f"workflow:{workflow}",
                    output__task__project_tag_id=task.project_tag_id,
                    output__task__owner_id=task.owner_id,
                    output__task__status="succeeded",
                )
                .select_related("output__task")
                .first()
            )
            if record is None or not any(
                identity in edge.get("resourceIds", [])
                and record.output_id in edge.get("outputIds", [])
                for edge in AgentWorkflowStep.objects.filter(
                    workflow_id=workflow,
                    kind="input_adapted",
                    compute_task_id=record.output.task_id,
                ).values_list("output_refs", flat=True)
            ):
                raise PermissionDenied("私有派生输入缺少可确认的工作流适配记录")
            public.update(inputs(record.output.task, depth + 1))
            if len(public) > MAX_INPUTS:
                raise ValidationError("监测成果的原始资料来源超过登记范围")
        visited.remove(current.pk)
        return public

    return sorted(inputs(task, 0))
