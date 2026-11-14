"""Registered historical fire observations, products and metadata-only time catalog."""

from copy import deepcopy
from datetime import date, timedelta
import re
import sqlite3

from django.core.exceptions import ValidationError, PermissionDenied
from apps.catalog.models import DataResource
from apps.catalog.serializers import serialize_resource
from apps.compute.models import ComputeImport
from apps.core.storage import table_data_path
from apps.projects.context import selected_project_id
from apps.projects.models import Project

IDENTIFIER = "wildfire-observe"
PRODUCTS = {
    "gwis_ba": ("GWIS火烧面积", "ha", "8day"),
    "gfed_ba": ("GFED火烧面积", "ha", "8day"),
    "fcci_ba": ("FCCI月度火烧面积", "ha", "monthly"),
    "cams_frpfire": ("CAMS火辐射功率密度", "W m-2", "8day"),
}


def observation_catalog(user):
    from .monitoring import configured_scenes, visible_resources

    project = Project.objects.get(pk=selected_project_id(), is_active=True)
    if "wildfire" not in configured_scenes(project):
        raise PermissionDenied("当前项目尚未开启野火场景")
    candidates = (
        visible_resources(
            user,
            DataResource.objects.filter(
                data_type="raster",
                file_format="ZARR",
                code__startswith="wildfire-seasfire-cube-",
            ).values("pk"),
        )
        .select_related("inventory_group")
        .order_by("-pk")
    )
    cube = candidates.first()
    if cube is None:
        return {"products": [], "times": []}
    tables = visible_resources(
        user,
        DataResource.objects.filter(
            data_type="table",
            file_format__iexact="SQLITE",
            inventory_group_id=cube.inventory_group_id,
            storage_path__startswith="wildfire_seasfire_time_",
        ).values("pk"),
    )
    time_resource = tables.order_by("-id").first()
    if time_resource is None:
        return {"cube": serialize_resource(cube), "products": [], "times": []}
    if not re.fullmatch("[a-zA-Z_][a-zA-Z0-9_]*", time_resource.storage_path):
        raise ValidationError("时间索引表名无效")
    with sqlite3.connect(
        table_data_path("data.sqlite").as_uri() + "?mode=ro", uri=True
    ) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            'SELECT time_index,date,gwis_ba_valid_mask,gfed_ba_valid_mask,fcci_ba_valid_mask FROM "'
            + time_resource.storage_path
            + '" ORDER BY time_index LIMIT 1000'
        ).fetchall()
    times = []
    for index, row in enumerate(rows):
        begin = date.fromisoformat(row["date"])
        end = (
            date.fromisoformat(rows[index + 1]["date"]) - timedelta(days=1)
            if index + 1 < len(rows)
            else min(begin + timedelta(days=7), date(begin.year, 12, 31))
        )
        times.append(
            {
                "index": row["time_index"],
                "date": begin.isoformat(),
                "endDate": end.isoformat(),
                "validProducts": [
                    key
                    for key in PRODUCTS
                    if key == "cams_frpfire" or row[key + "_valid_mask"] == 1
                ],
            }
        )
    return {
        "cube": serialize_resource(cube),
        "timeIndexResource": serialize_resource(time_resource),
        "products": [
            {"key": key, "label": label, "unit": unit, "periodMode": mode}
            for key, (label, unit, mode) in PRODUCTS.items()
        ],
        "times": times,
    }


def normalize_observation(value):
    from .monitoring import optional_date

    required = {
        "product",
        "unit",
        "periodMode",
        "series",
        "activeCells",
        "validCells",
        "gridCells",
        "grid",
        "legend",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("product") not in PRODUCTS
    ):
        raise ValidationError("观测产品依据缺失")
    _, unit, mode = PRODUCTS[value["product"]]
    if value["unit"] != unit or value["periodMode"] != mode:
        raise ValidationError("观测单位或时间口径不符")
    for key in ("activeCells", "validCells", "gridCells"):
        if type(value[key]) is not int or value[key] < 0:
            raise ValidationError("格网计数无效")
    if not value["activeCells"] <= value["validCells"] <= value["gridCells"]:
        raise ValidationError("格网计数不一致")
    if not isinstance(value["series"], list) or not 1 <= len(value["series"]) <= 12:
        raise ValidationError("观测序列长度无效")
    for row in value["series"]:
        if not isinstance(row, dict) or set(row) != {
            "observedStart",
            "observedEnd",
            "value",
            "validCells",
            "activeCells",
            "unit",
        }:
            raise ValidationError("序列字段不符")
        if (
            optional_date(row["observedStart"], "观测开始") is None
            or optional_date(row["observedEnd"], "观测结束") is None
            or row["observedStart"] > row["observedEnd"]
            or row["unit"] != unit
        ):
            raise ValidationError("序列时段或单位不符")
        if row["value"] is not None and (
            type(row["value"]) not in (int, float) or not 0 <= row["value"] <= 1e300
        ):
            raise ValidationError("序列观测值无效")
        if (
            type(row["validCells"]) is not int
            or type(row["activeCells"]) is not int
            or not 0 <= row["activeCells"] <= row["validCells"] <= value["gridCells"]
        ):
            raise ValidationError("序列格网统计无效")
    grid = value["grid"]
    if (
        not isinstance(grid, dict)
        or set(grid) != {"width", "height", "transform", "crs"}
        or grid["crs"] != "EPSG:4326"
        or any(
            type(grid[key]) is not int or not 1 <= grid[key] <= maximum
            for key, maximum in [("width", 1440), ("height", 720)]
        )
        or grid["width"] * grid["height"] != value["gridCells"]
    ):
        raise ValidationError("观测格网依据无效")
    transform = grid["transform"]
    if (
        not isinstance(transform, list)
        or len(transform) != 6
        or any(type(v) not in (int, float) or not -1e6 < v < 1e6 for v in transform)
        or transform[1:] != [0.25, 0, transform[3], 0, -0.25]
    ):
        raise ValidationError("观测格网变换无效")
    legend = value["legend"]
    if not isinstance(legend, list) or not 1 <= len(legend) <= 8:
        raise ValidationError("观测分级图例无效")
    seen = set()
    for row in legend:
        if (
            not isinstance(row, dict)
            or set(row) != {"code", "name", "rgba"}
            or type(row["code"]) is not int
            or not 0 <= row["code"] <= 255
            or row["code"] in seen
            or not isinstance(row["name"], str)
            or not 1 <= len(row["name"]) <= 128
            or not isinstance(row["rgba"], list)
            or len(row["rgba"]) != 4
            or any(type(v) is not int or not 0 <= v <= 255 for v in row["rgba"])
        ):
            raise ValidationError("观测图例编码与颜色无效")
        seen.add(row["code"])
    return value


def register_import(record_id):
    from .monitoring import register_product, configured_scenes

    record = ComputeImport.objects.select_related(
        "output__task__version__algorithm", "resource", "requested_by"
    ).get(pk=record_id)
    task = record.output.task
    if (
        record.status != "ready"
        or task.trial
        or record.output.key != "observation"
        or task.version.algorithm.identifier != IDENTIFIER
    ):
        return
    project = Project.objects.get(pk=selected_project_id())
    if "wildfire" not in configured_scenes(project):
        return
    facts = record.output.metadata.get("knowledgeFacts", {}).get("wildfireObservation")
    if not isinstance(facts, dict):
        raise ValidationError("观测成果缺少实际时空依据")
    observation = {
        key: deepcopy(facts[key])
        for key in (
            "product",
            "unit",
            "periodMode",
            "series",
            "activeCells",
            "validCells",
            "gridCells",
            "grid",
            "legend",
        )
    }
    sources = list(
        task.input_records.exclude(resource=None).values_list("resource_id", flat=True)
    )
    current = facts["current"]
    quantity = "火烧面积" if facts["unit"] == "ha" else "平均火辐射功率密度"
    value = {
        "schemaVersion": 1,
        "code": "wildfire-observation-" + str(task.pk) + "-" + str(record.output_id),
        "name": record.resource.name,
        "resourceId": record.resource_id,
        "scene": "wildfire",
        "kind": "observation",
        "quality": "passed",
        "observedStart": current["observedStart"],
        "observedEnd": current["observedEnd"],
        "sourceResourceIds": sources,
        "sourceLabel": PRODUCTS[facts["product"]][0] + " / SeasFire原始观测",
        "limitations": ["原始格网为0.25度，按选中研究区统计。"],
        "interpretation": f"所选时期研究区{quantity}{current['value']:,.3f} {facts['unit']}，共{facts['activeCells']}个正观测值格网。",
        "statistics": facts["statistics"],
        "statisticsMethod": "面积按源ha值直接求和；FRP按有效格网平均；FCCI按月平均重复记录；缺测独立于零值。",
        "model": None,
        "threshold": None,
        "observation": observation,
        "timing": {
            "inputThrough": current["observedEnd"],
            "validStart": None,
            "validEnd": None,
            "evidence": "原始时间坐标、产品有效掩膜及真实时段。",
        },
    }
    return register_product(record.requested_by, value, computed_import=record)


def attach_related(items, user):
    from .monitoring import visible_resources

    base = list(
        ComputeImport.objects.filter(
            resource_id__in=[i["resourceId"] for i in items],
            status="ready",
            output__key="observation",
        ).select_related("output__task__version__algorithm")
    )
    tasks = {
        row.output.task_id: row.resource_id
        for row in base
        if row.output.task.version.algorithm.identifier == IDENTIFIER
    }
    rows = list(
        ComputeImport.objects.filter(
            output__task_id__in=tasks,
            output__key__in=["classification", "statistics", "series"],
            output__expired=False,
            status="ready",
        ).select_related("output", "resource")
    )
    allowed = {
        resource.pk: resource
        for resource in visible_resources(user, [row.resource_id for row in rows])
    }
    mapping = {}
    for row in rows:
        if row.resource_id in allowed:
            mapping.setdefault(tasks[row.output.task_id], []).append(
                {
                    "role": row.output.key,
                    "resource": serialize_resource(allowed[row.resource_id]),
                }
            )
    for item in items:
        item["attachments"] = mapping.get(item["resourceId"], [])
