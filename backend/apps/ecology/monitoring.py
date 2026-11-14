"""Project-scoped handoff of catalogued remote-sensing products."""

from copy import deepcopy
from datetime import date
import hashlib
import json
import math
import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.audit.service import log_operation
from apps.catalog.models import DataResource, task_resource_q
from apps.catalog.permissions import filter_accessible
from apps.catalog.serializers import serialize_resource
from apps.projects.context import is_superadmin, selected_project_id
from apps.projects.features import MONITOR_FEATURE
from apps.projects.models import Project, ProjectFeature
from .models import RemoteSensingProduct

# CONFIGURATION: bounded metadata only; raster and vector reads use catalog APIs.
SCENES = {
    "landcover": {
        "title": "地表覆盖解译",
        "route": [
            "选择影像",
            "影像与模型预检",
            "模型解译与分类合成",
            "结果核验与统计",
            "分类成果入库",
            "地图与大屏展示",
        ],
    },
    "spartina": {
        "title": "互花米草监测",
        "route": [
            "选区与资料",
            "输入准备",
            "模型识别",
            "斑块统计",
            "变化核验",
            "成果发布",
        ],
    },
    "wildfire": {
        "title": "野火风险研判",
        "route": [
            "日期与区域",
            "变量准备",
            "风险推理",
            "区域汇总",
            "历史验证",
            "成果发布",
        ],
    },
}
METRICS = {
    "landcover": {
        "valid_area_km2": ("有效统计面积", "km²"),
        "classified_area_km2": ("已提取地类面积", "km²"),
        "class_count": ("成果类别", "类"),
    },
    "spartina": {
        "area_ha": ("分布面积", "ha"),
        "patch_count": ("斑块数量", "个"),
        "valid_area_km2": ("有效统计面积", "km²"),
        "coverage_percent": ("有效区覆盖比例", "%"),
    },
    "wildfire": {
        "mean_probability": ("有效区平均概率", ""),
        "high_risk_area_km2": ("阈值以上区域面积", "km²"),
        "valid_coverage_percent": ("有效数据覆盖率", "%"),
        "burned_area_ha": ("观测烧毁面积", "ha"),
        "frp_w_m2": ("观测火辐射功率密度", "W m-2"),
    },
}
MAX_CANDIDATES = 200
MAX_PAGE = 60
MAX_MANIFEST_BYTES = 64 * 1024
FIELDS = {
    "schemaVersion",
    "code",
    "name",
    "resourceId",
    "scene",
    "kind",
    "quality",
    "observedStart",
    "observedEnd",
    "sourceResourceIds",
    "sourceLabel",
    "limitations",
    "interpretation",
    "statistics",
    "classification",
    "statisticsMethod",
    "model",
    "threshold",
    "timing",
}


def invalid(message):
    raise ValidationError(message)


def text(value, name, maximum=1000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        invalid(f"{name}须为非空且有界文本")
    return value.strip()


def optional_date(value, name):
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        invalid(f"{name}须为 YYYY-MM-DD 或 null")
    if parsed.isoformat() != value:
        invalid(f"{name}须为 YYYY-MM-DD")
    return value


def configured_scenes(project):
    feature = ProjectFeature.objects.filter(key=MONITOR_FEATURE).first()
    setting = (
        project.feature_settings.filter(feature=feature).first() if feature else None
    )
    if (
        not feature
        or not project.is_active
        or not (feature.globally_enabled or (setting and setting.enabled))
    ):
        raise PermissionDenied("当前项目尚未开启监测大屏")
    config = setting.config if setting else None
    if not isinstance(config, dict):
        return []
    if config.get("source") == "remote_sensing_products":
        return config.get("scenes", ["spartina", "wildfire"])
    return config.get("scenes", [])


def normalize_product(value):
    if not isinstance(value, dict) or set(value) - FIELDS:
        invalid("监测成果不是对象或包含未知字段")
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError):
        invalid("监测成果不是有效 JSON")
    if len(encoded) > MAX_MANIFEST_BYTES:
        invalid("监测成果清单超过64KiB")
    item = deepcopy(value)
    if type(item.get("schemaVersion")) is not int or item["schemaVersion"] != 1:
        invalid("监测成果协议版本无效")
    for field, maximum in (
        ("code", 120),
        ("name", 180),
        ("sourceLabel", 500),
        ("interpretation", 3000),
    ):
        item[field] = text(item.get(field), field, maximum)
    if not re.fullmatch(r"[a-z][a-z0-9_-]{1,119}", item["code"]):
        invalid("产品编码须为稳定英文 slug")
    if type(item.get("resourceId")) is not int or item["resourceId"] <= 0:
        invalid("resourceId须为正整数")
    scene = item.get("scene")
    if not isinstance(scene, str) or scene not in SCENES:
        invalid("监测场景无效")
    if item.get("kind") not in ("historical", "model", "observation") or item.get(
        "quality"
    ) not in ("unverified", "passed", "needs_review"):
        invalid("产品性质或质量状态无效")
    for key in ("observedStart", "observedEnd"):
        item[key] = optional_date(item.get(key), key)
    if bool(item["observedStart"]) != bool(item["observedEnd"]) or (
        item["observedStart"] and item["observedStart"] > item["observedEnd"]
    ):
        invalid("观测区间须完整且起止有序；未知时间使用null")
    ids = item.get("sourceResourceIds")
    if (
        not isinstance(ids, list)
        or not ids
        or len(ids) > 32
        or any(type(x) is not int or x <= 0 for x in ids)
        or len(set(ids)) != len(ids)
    ):
        invalid("sourceResourceIds须为1至32个不同资源ID")
    limitations = item.get("limitations")
    if not isinstance(limitations, list) or not 1 <= len(limitations) <= 8:
        invalid("须明确1至8条成果局限")
    item["limitations"] = [text(x, "成果局限", 500) for x in limitations]
    statistics = item.get("statistics", {})
    if not isinstance(statistics, dict) or set(statistics) - set(METRICS[scene]):
        invalid("统计项不属于当前场景")
    for key, number in statistics.items():
        if number is None:
            continue
        maximum = (
            1 if key == "mean_probability" else 100 if "percent" in key else math.inf
        )
        if type(number) not in (int, float) or not 0 <= number <= min(maximum, 1e300):
            invalid(f"统计项{key}超出范围或不是有限数值")
        if key == "patch_count" and number != int(number):
            invalid("斑块数量须为整数")
    item["statistics"] = statistics
    if scene == "landcover":
        from .landcover import normalize_classification

        item["classification"] = normalize_classification(item.get("classification"))
        total = sum(row["areaKm2"] for row in item["classification"]["categories"])
        valid = statistics.get("valid_area_km2")
        if valid is None or total > valid + max(1e-6, valid * 1e-6):
            invalid("类别面积不能超过有效统计面积")
        if item["classification"]["mode"] == "complete" and abs(total - valid) > max(
            1e-6, valid * 1e-6
        ):
            invalid("完整解译的类别面积与有效区不一致")
    elif item.get("classification") is not None:
        invalid("当前场景不接受地表分类统计")
    item["statisticsMethod"] = text(item.get("statisticsMethod"), "统计口径", 1000)
    threshold = item.get("threshold")
    if threshold is not None and (
        type(threshold) not in (int, float) or not 0 <= threshold <= 1
    ):
        invalid("阈值须在0至1之间或为null")
    item["threshold"] = threshold
    if statistics.get("high_risk_area_km2") is not None and threshold is None:
        invalid("阈值以上面积须声明实际阈值")
    model = item.get("model")
    if model is not None:
        if not isinstance(model, dict) or set(model) != {
            "name",
            "version",
            "checkpointSha256",
            "variant",
            "forecastLeadDays",
        }:
            invalid("模型须包含名称、版本、权重摘要、变体和提前天数")
        for key in ("name", "version", "variant"):
            model[key] = text(model[key], key, 160)
        if not isinstance(model["checkpointSha256"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", model["checkpointSha256"]
        ):
            invalid("模型权重须声明SHA-256")
        lead = model["forecastLeadDays"]
        if lead is not None and (type(lead) is not int or not 0 <= lead <= 366):
            invalid("预测提前天数须为0至366整数或null")
    if item["kind"] == "model" and model is None:
        invalid("模型结果须提供实际模型版本与权重摘要")
    item["model"] = model
    timing = item.get(
        "timing",
        {
            "inputThrough": None,
            "validStart": None,
            "validEnd": None,
            "evidence": "时效未核实",
        },
    )
    if not isinstance(timing, dict) or set(timing) != {
        "inputThrough",
        "validStart",
        "validEnd",
        "evidence",
    }:
        invalid("时效字段无效")
    for key in ("inputThrough", "validStart", "validEnd"):
        timing[key] = optional_date(timing[key], key)
    timing["evidence"] = text(timing["evidence"], "时间依据", 1000)
    if bool(timing["validStart"]) != bool(timing["validEnd"]):
        invalid("预测有效区间须完整")
    if timing["validStart"] and (
        not model
        or model["forecastLeadDays"] is None
        or not timing["inputThrough"]
        or timing["validEnd"] < timing["validStart"]
    ):
        invalid("预测有效期须有模型时效与输入截至时间依据")
    if model and model["forecastLeadDays"] is not None:
        if (
            not timing["validStart"]
            or (
                date.fromisoformat(timing["validStart"])
                - date.fromisoformat(timing["inputThrough"])
            ).days
            != model["forecastLeadDays"]
        ):
            invalid("预测提前天数须与输入截至时间、有效开始日期一致")
    item["timing"] = timing
    return item


def visible_resources(user, ids):
    return filter_accessible(
        DataResource.objects.filter(
            pk__in=ids, project_tag_id=selected_project_id(), status="active"
        )
        .exclude(task_resource_q())
        .select_related("category", "category__parent"),
        user,
    )


def validate_model_import(resource, item):
    if item["kind"] != "model":
        return
    from apps.compute.models import ComputeImport
    from apps.compute.packages import ComputeError
    from apps.compute.quality import require_automatic_quality

    record = (
        ComputeImport.objects.filter(
            resource=resource,
            status="ready",
            output__expired=False,
            output__task__status="succeeded",
            output__task__trial=False,
            output__task__project_tag_id=resource.project_tag_id,
        )
        .select_related("output__task__version")
        .first()
    )
    if not resource.is_compute_result or record is None:
        invalid(
            "新模型结果须先通过计算中心质量门禁和标准入库；原有外部成果按historical登记"
        )
    try:
        require_automatic_quality(record.output)
    except ComputeError as error:
        invalid(str(error))
    actual_inputs = set(
        record.output.task.input_records.exclude(resource_id=None).values_list(
            "resource_id", flat=True
        )
    )
    if not actual_inputs <= set(item["sourceResourceIds"]):
        invalid("模型产品必须保留计算任务的全部来源资源")
    check = record.output.metadata.get("qualityCheck") or {}
    if item["quality"] == "passed" and check.get("status") != "passed":
        invalid("不能将缺少通过证据的模型产品标为已核验")


@transaction.atomic
def register_product(user, value, *, computed_import=None):
    if computed_import is not None:
        if (
            computed_import.requested_by_id != user.pk
            or computed_import.status != "ready"
            or computed_import.output.task.owner_id != user.pk
            or computed_import.output.task.project_tag_id != selected_project_id()
            or computed_import.output.task.version.algorithm.identifier
            != "landcover-unet-infer"
            or computed_import.resource_id != value.get("resourceId")
            or value.get("scene") != "landcover"
        ):
            raise PermissionDenied("模型产品与本人实际入库任务不一致")
    elif not is_superadmin(user):
        raise PermissionDenied("只有超级管理员可以登记监测成果")
    item = normalize_product(value)
    project = Project.objects.select_for_update().get(pk=selected_project_id())
    if item["scene"] not in configured_scenes(project):
        invalid("当前项目尚未配置此遥感监测场景")
    ids = set(item["sourceResourceIds"]) | {item["resourceId"]}
    resources = {row.pk: row for row in visible_resources(user, ids)}
    if resources.keys() != ids:
        raise PermissionDenied("成果及全部来源须为当前项目可见的启用资源")
    resource = resources[item["resourceId"]]
    if (
        resource.data_type not in ("vector", "raster")
        or resource.spatial_class != "spatial"
        or not resource.storage_path
    ):
        invalid("监测地图须绑定已入库的空间矢量或栅格资源")
    validate_model_import(resource, item)
    digest = hashlib.sha256(
        json.dumps(item, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    previous = RemoteSensingProduct.objects.filter(
        project_tag=project, product_code=item["code"]
    ).first()
    if previous:
        if previous.metadata.get("monitoringHash") != digest:
            invalid("产品编码已存在且内容不同；请使用新编码保存新成果")
        return previous, False
    row = RemoteSensingProduct.objects.create(
        project_tag=project,
        product_code=item["code"],
        name=item["name"],
        product_type=f"monitoring_{item['scene']}",
        data_resource=resource,
        acquired_on=item["observedStart"]
        if item["observedStart"] == item["observedEnd"]
        else None,
        period_start=item["observedStart"],
        period_end=item["observedEnd"],
        metadata={"monitoring": item, "monitoringHash": digest},
    )
    log_operation(
        user,
        "生态监测",
        "登记成果",
        "success",
        row.name,
        target_type="remote_sensing_product",
        target_id=row.pk,
        target_code=row.product_code,
        target_name=row.name,
    )
    return row, True


def monitoring_snapshot(user, scene, before_id=None, limit=MAX_PAGE):
    project = Project.objects.get(pk=selected_project_id(), is_active=True)
    scenes = configured_scenes(project)
    if scene not in scenes:
        raise PermissionDenied("当前项目尚未配置此遥感监测场景")
    query = (
        RemoteSensingProduct.objects.filter(
            project_tag=project,
            product_type=f"monitoring_{scene}",
            data_resource__in=visible_resources(
                user, DataResource.objects.values("pk")
            ),
        )
        .select_related(
            "data_resource",
            "data_resource__category",
            "data_resource__category__parent",
        )
        .order_by("-pk")
    )
    if before_id is not None:
        query = query.filter(pk__lt=before_id)
    candidates = list(query[: MAX_CANDIDATES + 1])
    normalized = {}
    all_ids = set()
    for row in candidates[:MAX_CANDIDATES]:
        try:
            item = normalize_product(row.metadata.get("monitoring"))
        except (ValidationError, AttributeError):
            continue
        if item["scene"] != scene or item["resourceId"] != row.data_resource_id:
            continue
        normalized[row.pk] = item
        all_ids.update(item["sourceResourceIds"])
    allowed = set(visible_resources(user, all_ids).values_list("pk", flat=True))
    items = []
    examined = 0
    for row in candidates[:MAX_CANDIDATES]:
        examined += 1
        item = normalized.get(row.pk)
        if item is None or not set(item["sourceResourceIds"]) <= allowed:
            continue
        items.append(
            {
                "id": row.pk,
                **item,
                "resource": serialize_resource(row.data_resource),
                "registeredAt": row.created_at.isoformat(),
                "metrics": [
                    {
                        "key": key,
                        "label": label,
                        "unit": unit,
                        "value": item["statistics"].get(key),
                    }
                    for key, (label, unit) in METRICS[scene].items()
                ],
            }
        )
        if len(items) >= limit:
            break
    more = examined < len(candidates)
    launch = {}
    if scene == "landcover":
        from apps.business_flows.scopes import available_flows
        from apps.business_flows.landcover import CODE

        flow = (
            available_flows()
            .filter(code=CODE, is_active=True, project_tag_id=project.pk)
            .select_related("current_version")
            .first()
        )
        if flow and flow.current_version and flow.current_version.status == "published":
            launch["businessFlow"] = {
                "definitionId": flow.pk,
                "versionId": flow.current_version_id,
                "title": flow.name,
                "goal": flow.description,
            }
        from django.db.models import Q

        source_ids = {
            identity for item in items for identity in item["sourceResourceIds"]
        }
        recommended = list(
            filter_accessible(
                DataResource.objects.filter(
                    status="active",
                    data_type__in=["raster", "vector"],
                    is_compute_result=False,
                )
                .filter(
                    Q(source__startswith="landcover-handoff:") | Q(pk__in=source_ids)
                )
                .exclude(task_resource_q())
                .select_related("category", "inventory_group")
                .prefetch_related("access_groups"),
                user,
            ).order_by("id")[:128]
        )
        launch["inputResources"] = [
            serialize_resource(row) for row in recommended if row.data_type == "raster"
        ]
        boundary = next(
            (
                row
                for row in recommended
                if row.data_type == "vector"
                and row.source.startswith("landcover-handoff:")
            ),
            None,
        )
        if boundary:
            launch["inputBoundary"] = serialize_resource(boundary)

    return {
        "projectId": project.pk,
        "scene": scene,
        "title": SCENES[scene]["title"],
        "route": SCENES[scene]["route"],
        "items": items,
        "nextBeforeId": candidates[examined - 1].pk if more and examined else None,
        **launch,
    }
