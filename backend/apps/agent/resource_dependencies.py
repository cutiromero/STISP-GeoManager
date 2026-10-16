"""Active conversation references used by catalog deletion protection."""

from .interactions import BLOCKING
from django.db.models import Q

from .models import AgentComputeFollowup, AgentRun


def active_run_reasons(resource_id):
    if (
        AgentComputeFollowup.objects.filter(
            status__in=["waiting_compute", "waiting_import", "reading_result"],
        )
        .filter(
            Q(task__input_records__resource_id=resource_id)
            | Q(task__outputs__import_record__resource_id=resource_id)
        )
        .exists()
    ):
        return ["智能体仍在处理计算或入库结果，请完成或停止后续处理后再删除"]
    for run in AgentRun.objects.filter(status__in=BLOCKING):
        references = set(run.resource_ids or [])
        references.update(
            item.get("resourceId") for item in run.evidence if isinstance(item, dict)
        )
        references.update((run.compute_intent or {}).get("inputs", {}).values())
        references.update(
            run.compute_followups.values_list(
                "task__input_records__resource_id", flat=True
            )
        )
        references.update(
            run.compute_followups.values_list(
                "task__outputs__import_record__resource_id", flat=True
            )
        )
        if resource_id in references:
            return ["正在执行或等待继续的智能体任务引用该数据"]
    return []
