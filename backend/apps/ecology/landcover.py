"""Publish only standard, successful land-cover computation outputs."""

import hashlib
import json
import math
import re

from django.core.exceptions import PermissionDenied, ValidationError

from apps.compute.models import ComputeImport
from apps.projects.context import selected_project_id
from apps.projects.models import Project

CODES = {1: "裸地", 2: "耕地", 4: "林地", 5: "水体", 6: "建筑", 8: "道路"}


def normalize_classification(value):
    if not isinstance(value, dict) or set(value) != {
        "mode",
        "categories",
        "priority",
        "models",
    }:
        raise ValidationError("地表覆盖成果缺少分类、优先级或模型依据")
    if (
        not isinstance(value["mode"], str)
        or value["mode"] not in {"complete", "extract"}
        or not isinstance(value["categories"], list)
        or not 1 <= len(value["categories"]) <= 6
    ):
        raise ValidationError("地表覆盖分类模式或类别数量无效")
    seen = set()
    for row in value["categories"]:
        if not isinstance(row, dict) or set(row) != {
            "code",
            "name",
            "pixelCount",
            "areaKm2",
            "percent",
            "color",
        }:
            raise ValidationError("类别统计字段无效")
        code = row["code"]
        if (
            type(code) is not int
            or code in seen
            or code not in CODES
            or row["name"] != CODES[code]
        ):
            raise ValidationError("地类编码或名称无效")
        seen.add(code)
        if type(row["pixelCount"]) is not int or row["pixelCount"] < 0:
            raise ValidationError("分类像元数无效")
        for field in ["areaKm2", "percent"]:
            if (
                type(row[field]) not in {int, float}
                or not math.isfinite(row[field])
                or row[field] < 0
            ):
                raise ValidationError("类别统计须为有限非负数")
        if (
            row["percent"] > 100
            or not isinstance(row["color"], str)
            or not re.fullmatch(r"#[a-fA-F0-9]{6}", row["color"])
        ):
            raise ValidationError("类别占比或颜色无效")
    if value["mode"] == "complete" and seen != set(CODES):
        raise ValidationError("完整解译须包含六类统计")
    if value["priority"] != ["建筑", "水体", "耕地", "林地", "道路"]:
        raise ValidationError("合成优先级不符合交付规则")
    if not isinstance(value["models"], list) or not 1 <= len(value["models"]) <= 5:
        raise ValidationError("模型依据无效")
    names = set()
    for row in value["models"]:
        if (
            not isinstance(row, dict)
            or set(row) != {"name", "sha256"}
            or not isinstance(row["name"], str)
            or row["name"] not in {"building", "water", "farmland", "forest", "road"}
            or row["name"] in names
            or not re.fullmatch(r"[a-f0-9]{64}", str(row["sha256"]))
        ):
            raise ValidationError("模型成员摘要无效")
        names.add(row["name"])
    return value


def register_import(record_id):
    from .monitoring import configured_scenes, register_product

    record = ComputeImport.objects.select_related(
        "output__task__version__algorithm", "requested_by", "resource"
    ).get(pk=record_id)
    output = record.output
    task = output.task
    if (
        record.status != "ready"
        or task.trial
        or output.key != "classification"
        or task.version.algorithm.identifier != "landcover-unet-infer"
    ):
        return
    project = Project.objects.get(pk=selected_project_id())
    try:
        if "landcover" not in configured_scenes(project):
            return
    except PermissionDenied:
        return
    data = output.metadata.get("knowledgeFacts", {}).get("landcover")
    if not isinstance(data, dict):
        raise ValidationError("地表覆盖成果没有实际统计依据")
    source_ids = list(
        task.input_records.exclude(resource=None).values_list("resource_id", flat=True)
    )
    classification = {
        "mode": data["mode"],
        "categories": data["statistics"],
        "priority": data["priority"],
        "models": [
            {"name": row["class"], "sha256": row["modelSha256"]}
            for row in data["models"]
        ],
    }
    digest = hashlib.sha256(
        json.dumps(classification["models"], sort_keys=True).encode()
    ).hexdigest()
    value = {
        "schemaVersion": 1,
        "code": "landcover-" + str(task.pk) + "-" + str(output.pk),
        "name": record.resource.name,
        "resourceId": record.resource_id,
        "scene": "landcover",
        "kind": "model",
        "quality": "passed",
        "observedStart": None,
        "observedEnd": None,
        "sourceResourceIds": source_ids,
        "sourceLabel": "原始RGB影像与已登记UNet模型组",
        "limitations": ["裸地为五类模型之外的有效剩余区。"],
        "interpretation": "按固定优先级合成建筑、水体、耕地、林地、道路及剩余区。",
        "statistics": {
            "valid_area_km2": data["validAreaKm2"],
            "classified_area_km2": sum(r["areaKm2"] for r in data["statistics"]),
            "class_count": len(data["statistics"]),
        },
        "statisticsMethod": "按原始米制投影网格统计最终类别像元，排除无效区。",
        "model": {
            "name": "UNet地表覆盖模型组",
            "version": task.version.version,
            "variant": "完整六类" if data["mode"] == "complete" else "专项提取",
            "checkpointSha256": digest,
            "forecastLeadDays": None,
        },
        "classification": classification,
    }
    return register_product(record.requested_by, value, computed_import=record)
