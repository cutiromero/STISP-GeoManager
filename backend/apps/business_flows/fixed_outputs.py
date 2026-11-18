"""Stage validated products in the existing import queue, never publish them."""

from django.db import transaction

from apps.compute.models import ComputeImport
from apps.compute.packages import ComputeError
from apps.compute.services import request_output_import
from .state import emit, locked_workflow, WorkflowControlChanged


def prepare_delivery(workflow, user, node, task):
    expected = {
        row["name"]: row["semanticType"] for row in node["contract"]["requiredOutputs"]
    }
    outputs = {
        row.key: row
        for row in task.outputs.filter(key__in=expected, expired=False).select_related(
            "task"
        )
    }
    if outputs.keys() != expected.keys() or any(
        outputs[key].kind != kind for key, kind in expected.items()
    ):
        raise ComputeError("计算未生成全部必交付成果，或成果类型不符合已发布流程")
    records = {
        row.output_id: row
        for row in ComputeImport.objects.filter(output__in=outputs.values())
    }
    if any(row.status in {"failed", "deleted"} for row in records.values()):
        error = next(
            row for row in records.values() if row.status in {"failed", "deleted"}
        )
        raise ComputeError("成果入库未完成：" + (error.error or error.status))
    if len(records) == len(outputs) and all(
        row.status == "ready" and row.resource_id for row in records.values()
    ):
        return True
    if len(records) < len(outputs):
        with transaction.atomic():
            current = locked_workflow(workflow.pk)
            if (
                current.cancel_requested
                or current.pause_requested
                or current.policy_snapshot.get("businessFlowControlEpoch", 0)
                != workflow.policy_snapshot.get("businessFlowControlEpoch", 0)
            ):
                raise WorkflowControlChanged("新的用户决定阻止了成果入库")
            for output in outputs.values():
                if output.pk not in records:
                    request_output_import(
                        user, output, request_source=f"workflow:{workflow.pk}"
                    )
            workflow.status, workflow.detail = (
                "waiting_compute",
                "计算完成，正在组织本次任务的图表成果",
            )
            emit(workflow, "executor", node["id"], "preparing_outputs", workflow.detail)
    return False
