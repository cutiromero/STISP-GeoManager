"""A batch goal finishes only when its real outputs cover every selected source."""

from apps.compute.models import ComputeInput
from apps.compute.packages import ComputeError


def require_source_coverage(workflow, node, item):
    coverage = (node.get("contract") or {}).get("sourceCoverage")
    if not coverage:
        return
    role = coverage["inputRole"]
    expected = {
        identity
        for key, identity in workflow.plan.get("inputs", {}).items()
        if key == role or key.startswith(role + ":")
    }
    task_ids = item.get("toolLoop", {}).get("taskIds", [])
    covered = set(
        ComputeInput.objects.filter(
            task_id__in=task_ids,
            task__owner_id=workflow.owner_id,
            task__project_tag_id=workflow.project_tag_id,
            task__status="succeeded",
            task__outputs__key=coverage["outputKey"],
            task__outputs__expired=False,
            resource_id__in=expected,
        ).values_list("resource_id", flat=True)
    )
    missing = expected - covered
    if not expected or missing:
        raise ComputeError(
            "当前目标仍有资料未完成实际计算："
            + ",".join(str(identity) for identity in sorted(missing))
        )
