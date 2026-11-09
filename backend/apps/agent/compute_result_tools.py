"""Read immutable, authorized calculation outputs before model interpretation."""

import json

from django.core.exceptions import PermissionDenied, ValidationError

from apps.compute.models import ComputeOutput
from apps.compute.packages import ComputeError, checksum
from apps.compute.serializers import output_data
from apps.compute.result_reads import table_page, raster_statistics
from apps.core.storage import app_path
from .compute_tools import authorized_task
from .selections import require_task_selection


def read_output(run, user, policy, args, *, workflow=None):
    output_id = args.get("outputId")
    offset, limit = args.get("offset", 0), args.get("limit", 30)
    if (
        type(output_id) is not int
        or output_id < 1
        or type(offset) is not int
        or offset < 0
        or type(limit) is not int
        or not 1 <= limit <= 50
    ):
        raise ValidationError("outputId须为真实输出编号，offset从0开始，limit为1至50")
    output = (
        ComputeOutput.objects.select_related("task")
        .filter(pk=output_id, task__project_tag_id=run.project_tag_id)
        .first()
    )
    if not output:
        raise PermissionDenied("结果不存在或不属于当前项目")
    if workflow is not None and (
        run.research_workflow_id != workflow.pk
        or run.owner_id != workflow.owner_id
        or run.project_tag_id != workflow.project_tag_id
    ):
        raise PermissionDenied("结果读取的业务流与发起对话不一致")
    task = authorized_task(user, output.task_id, policy, run=run, workflow=workflow)
    if workflow is None:
        require_task_selection(run, task)
    path = app_path(output.path)
    if task.status != "succeeded" or output.expired or not path.is_file():
        raise ComputeError("结果未成功、已过期或文件缺失，请查看真实任务状态")
    if path.is_symlink() or checksum(path) != output.checksum:
        raise ComputeError("计算结果文件内容已变化，请重新检查")
    result = {
        "taskId": str(task.id),
        "output": output_data(output),
        "checkedChecksum": output.checksum,
    }
    if output.kind == "table":
        rows = []
        with table_page(path, offset, limit, expected_checksum=output.checksum) as page:
            fields, total = page["columns"], page["total"]
            for row in page["rows"]:
                proposed = {
                    **result,
                    "columns": fields,
                    "rows": [*rows, row],
                }
                if (
                    len(rows) >= limit
                    or len(json.dumps(proposed, ensure_ascii=False).encode()) > 22000
                ):
                    break
                rows.append(row)
        if total > offset and not rows:
            raise ValidationError("单行结果超出模型读取容量，请使用结果预览查看")
        next_offset = offset + len(rows) if offset + len(rows) < total else None
        result.update(
            columns=fields,
            rows=rows,
            total=total,
            offset=offset,
            count=len(rows),
            nextOffset=next_offset,
            scope="all" if offset == 0 and next_offset is None else "page",
        )
    elif output.kind == "raster":
        from apps.raster.services.exceptions import RasterImportError

        try:
            info = raster_statistics(path, expected_checksum=output.checksum)
        except RasterImportError as exc:
            raise ComputeError("计算结果栅格统计读取失败，请查看结果预览") from exc
        result.update(
            scope="approximate_raster_statistics",
            statisticsNote="GDAL近似统计，仅支持描述本次输出的数值分布；无法单独证明生态变化原因。",
            size=info.get("size", []),
            bands=[
                {
                    "band": band.get("band"),
                    "type": band.get("type"),
                    "minimum": band.get("minimum"),
                    "maximum": band.get("maximum"),
                    "mean": band.get("mean"),
                    "stdDev": band.get("stdDev"),
                    "noDataValue": band.get("noDataValue"),
                    "statistics": {
                        key: value
                        for key, value in band.get("metadata", {}).get("", {}).items()
                        if key.startswith("STATISTICS_")
                    },
                }
                for band in info.get("bands", [])[:32]
            ],
        )
    else:
        result.update(
            scope="metadata",
            note="已校验实际结果文件；此工具仅返回该格式的真实元信息，具体内容请使用结果预览。",
        )
    if len(json.dumps(result, ensure_ascii=False).encode()) > 24000:
        raise ValidationError("结果元信息过大，请使用结果预览查看")
    return result, [(None, result)]
