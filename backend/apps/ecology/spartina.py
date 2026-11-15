"""Actual RF imports and their paired probability/statistics resources."""

from django.core.exceptions import PermissionDenied, ValidationError
from apps.compute.models import ComputeImport
from apps.projects.context import selected_project_id
from apps.projects.models import Project

IDENTIFIER = "spartina-rf-infer"


def normalize_extraction(value):
    if not isinstance(value, dict) or set(value) != {
        "method",
        "inputPeriods",
        "bounds",
        "validPixelCount",
        "targetPixelCount",
        "sklearnVersion",
    }:
        raise ValidationError("互花米草成果缺少模型输入与研究区依据")
    periods = value["inputPeriods"]
    if (
        value["method"] != "RF"
        or not isinstance(periods, list)
        or len(periods) != 3
        or any(not isinstance(row, str) or not 1 <= len(row) <= 120 for row in periods)
    ):
        raise ValidationError("互花米草方法或三时相组合不符")
    bounds = value["bounds"]
    if (
        not isinstance(bounds, list)
        or len(bounds) != 4
        or any(type(v) not in (int, float) for v in bounds)
        or not (
            -180 <= bounds[0] < bounds[2] <= 180 and -90 <= bounds[1] < bounds[3] <= 90
        )
    ):
        raise ValidationError("研究区边界无效")
    if (
        any(
            type(value[key]) is not int or value[key] < 0
            for key in ("validPixelCount", "targetPixelCount")
        )
        or value["targetPixelCount"] > value["validPixelCount"]
        or not isinstance(value["sklearnVersion"], str)
        or not 1 <= len(value["sklearnVersion"]) <= 50
    ):
        raise ValidationError("有效像元统计或运行版本无效")
    return value


def register_import(record_id):
    from .monitoring import configured_scenes, register_product

    record = ComputeImport.objects.select_related(
        "output__task__version__algorithm", "requested_by", "resource"
    ).get(pk=record_id)
    output, task = record.output, record.output.task
    if (
        record.status == "ready"
        and not task.trial
        and output.key == "probability"
        and task.version.algorithm.identifier == IDENTIFIER
    ):
        from apps.raster.models import RasterDataset
        from apps.raster.services.rules_engine import normalize_rules

        dataset = RasterDataset.objects.get(
            data_resource_id=record.resource_id, status="ready"
        )
        rules = {
            **dataset.default_rules,
            "mode": "pseudocolor",
            "bands": [1],
            "palette": "poplar",
            "stretch": {
                "enabled": True,
                "type": "minmax",
                "perBand": {"1": {"min": 0, "max": 1}},
            },
        }
        dataset.default_rules = normalize_rules(rules, dataset.processed_gdalinfo)
        dataset.save(update_fields=["default_rules"])
        return
    if (
        record.status != "ready"
        or task.trial
        or output.key != "classification"
        or task.version.algorithm.identifier != IDENTIFIER
    ):
        return
    project = Project.objects.get(pk=selected_project_id())
    try:
        if "spartina" not in configured_scenes(project):
            return
    except PermissionDenied:
        return
    from .models import RemoteSensingProduct

    previous = RemoteSensingProduct.objects.filter(
        product_code="spartina-" + str(task.pk) + "-" + str(output.pk),
        data_resource_id=record.resource_id,
    ).first()
    if previous:
        return register_product(
            record.requested_by, previous.metadata["monitoring"], computed_import=record
        )
    facts = output.metadata.get("knowledgeFacts", {}).get("spartina")
    if not isinstance(facts, dict):
        raise ValidationError("模型成果缺少真实统计依据")
    source_ids = list(
        task.input_records.exclude(resource=None).values_list("resource_id", flat=True)
    )
    extraction = {
        key: facts[key]
        for key in (
            "method",
            "inputPeriods",
            "bounds",
            "validPixelCount",
            "targetPixelCount",
            "sklearnVersion",
        )
    }
    area = facts["statistics"]["area_ha"]
    from .product_time import input_periods, interval

    begin, end = interval(input_periods(task))
    value = {
        "schemaVersion": 1,
        "code": "spartina-" + str(task.pk) + "-" + str(output.pk),
        "name": record.resource.name,
        "resourceId": record.resource_id,
        "scene": "spartina",
        "kind": "model",
        "quality": "passed",
        "observedStart": begin,
        "observedEnd": end,
        "sourceResourceIds": source_ids,
        "sourceLabel": "已选时相16波段原始影像与RF权重",
        "limitations": ["时相精度沿用原始资料登记，三期共同有效区参与统计。"],
        "interpretation": f"本研究区互花米草分布面积{area:,.2f} ha，按三季节共同有效区统计。",
        "statistics": facts["statistics"],
        "statisticsMethod": "原始WGS84网格椭球像元面积；三季节48特征共同有效区；8连通斑块。",
        "model": {
            "name": "互花米草随机森林",
            "version": task.version.version,
            "variant": "三季节48特征",
            "checkpointSha256": facts["modelSha256"],
            "forecastLeadDays": None,
        },
        "threshold": None,
        "extraction": extraction,
    }
    return register_product(record.requested_by, value, computed_import=record)


def attach_related(items, user):
    from .monitoring import visible_resources

    # Use exact classification -> real task relationships, never product order.
    records = list(
        ComputeImport.objects.filter(
            resource_id__in=[i["resourceId"] for i in items],
            status="ready",
            output__key="classification",
        ).select_related("output__task__version__algorithm")
    )
    tasks = {
        row.output.task_id: row.resource_id
        for row in records
        if row.output.task.version.algorithm.identifier == IDENTIFIER
    }
    siblings = list(
        ComputeImport.objects.filter(
            output__task_id__in=tasks,
            output__key__in=["probability", "statistics", "original"],
            status="ready",
            output__expired=False,
        ).select_related("resource", "output")
    )
    allowed = {
        r.pk: r for r in visible_resources(user, [row.resource_id for row in siblings])
    }
    from apps.catalog.serializers import serialize_resource

    by_resource = {}
    for row in siblings:
        if row.resource_id in allowed:
            by_resource.setdefault(tasks[row.output.task_id], []).append(
                {
                    "role": row.output.key,
                    "resource": serialize_resource(allowed[row.resource_id]),
                }
            )
    for item in items:
        item["attachments"] = by_resource.get(item["resourceId"], [])
