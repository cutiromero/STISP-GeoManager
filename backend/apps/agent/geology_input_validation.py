"""Read actual input metadata before creating or preparing a map review."""

import math

from pyproj import CRS
from pyproj.exceptions import CRSError

from apps.compute import data
from apps.compute.models import AlgorithmVersion
from apps.compute.packages import ComputeError
from apps.compute.services import agent_algorithm_allowed, allowed_algorithms

from .geology_reference import is_reference_resource
from .tools import resolve_resource

# These are the runtime input protocol in geology-map-check/review_logic.py.
MAP_FIELDS = {
    "feature_id",
    "formation",
    "region",
    "geologic_age",
    "class",
    "name",
    "code",
    "path",
}
COVERAGE_FIELDS = {
    "coverage_id",
    "role",
    "complete_coverage",
    "no_water",
    "no_uninvestigated",
    "region",
    "source",
    "source_locator",
}
RULE_FIELDS = {
    "rule_id",
    "kind",
    "name",
    "scope",
    "conditions",
    "exceptions",
    "evidence_id",
    "evidence_kind",
    "source",
    "source_locator",
    "region",
    "region_bbox_wgs84",
    "formation",
    "expected_age",
    "knowledge_seed",
}
ROLES = {
    "initial_map": ("待检查地质图", "vector", MAP_FIELDS),
    "coverage": ("制图覆盖范围与例外", "vector", COVERAGE_FIELDS),
    "rules": ("专家规则", "table", RULE_FIELDS),
}
DEFAULT_PARAMETERS = (
    {
        "key": "working_epsg",
        "label": "面积计算投影 EPSG",
        "type": "integer",
        "default": 32646,
        "min": 1,
        "max": 999999,
    },
    {
        "key": "max_changes",
        "label": "本轮修改数量上限",
        "type": "integer",
        "default": 2,
        "min": 1,
        "max": 10,
    },
    {
        "key": "max_gap_area_m2",
        "label": "漏填筛查面积上限（平方米）",
        "type": "number",
        "default": 300000,
        "min": 1,
        "max": 10000000,
    },
    {
        "key": "geometry_tolerance_m",
        "label": "空间核对容差（米）",
        "type": "number",
        "default": 0.01,
        "min": 0.000001,
        "max": 0.1,
    },
)


def _manifests(versions):
    if versions is not None:
        return [item["manifest"] for item in versions.values()]
    version = next(
        (
            item
            for item in AlgorithmVersion.objects.select_related("algorithm")
            .filter(
                algorithm__in=allowed_algorithms(),
                algorithm__identifier="geology-map-check",
                algorithm__enabled=True,
                status="published",
            )
            .order_by("-created_at", "-id")
            if agent_algorithm_allowed(item)
        ),
        None,
    )
    return [version.manifest] if version else []


def _validate_parameters(parameters, versions):
    manifests = _manifests(versions)
    declared = [item.get("parameters", []) for item in manifests]
    specs = [spec for group in declared for spec in group] or list(DEFAULT_PARAMETERS)
    keys = {spec["key"] for spec in specs}
    if set(parameters) - keys:
        raise ComputeError(
            "地质检查参数包含未声明字段：" + "、".join(sorted(set(parameters) - keys))
        )
    settings = {}
    for spec in specs:
        key, label = spec["key"], spec.get("label", spec["key"])
        value = parameters.get(key, spec.get("default"))
        if (
            type(value) not in (int, float)
            or (type(value) is float and not math.isfinite(value))
            or (spec["type"] == "integer" and type(value) is not int)
        ):
            raise ComputeError(
                label + "须为有效" + ("整数" if spec["type"] == "integer" else "数字")
            )
        if not spec.get("min", -math.inf) <= value <= spec.get("max", math.inf):
            raise ComputeError(
                label
                + f"超出允许范围（{spec.get('min', '-∞')}至{spec.get('max', '∞')}）"
            )
        settings[key] = value
    try:
        target = CRS.from_epsg(settings.get("working_epsg", 32646))
    except (CRSError, ValueError, TypeError) as exc:
        raise ComputeError(
            "面积计算投影 EPSG 不存在，请填写有效的米制投影代码"
        ) from exc
    if (
        not target.is_projected
        or len(target.axis_info) < 2
        or any(
            abs(axis.unit_conversion_factor - 1) > 1e-9 for axis in target.axis_info[:2]
        )
    ):
        raise ComputeError("面积计算投影须为米制投影，不能使用经纬度或英尺坐标系")


def validate_geology_inputs(
    user, policy, inputs, parameters, selected=(), *, versions=None
):
    """Validate structure here; runtime algorithms still check rows and geometry."""
    if not isinstance(inputs, dict) or set(inputs) != set(ROLES):
        raise ComputeError("请分别选择待检查地质图、制图覆盖范围与例外、专家规则")
    if inputs["initial_map"] == inputs["coverage"]:
        raise ComputeError("待检查地质图与制图覆盖范围不能选择同一份数据，请分别选择")
    _validate_parameters(parameters, versions)
    metadata = {}
    for role, (label, kind, required) in ROLES.items():
        resource = resolve_resource(user, policy, inputs[role], selected)
        if is_reference_resource(resource) or (resource.source or "").startswith(
            ("geology-review-reference:", "geology-review-acceptance:")
        ):
            raise ComputeError(label + "仅用于独立验收，不能作为检查或修正输入")
        if resource.status != "active":
            raise ComputeError(label + "已停用，请重新选择有效数据")
        if resource.data_type != kind:
            raise ComputeError(
                label + "须选择" + ("面矢量数据" if kind == "vector" else "规则表格")
            )
        try:
            info = data.candidate(resource)
        except Exception as exc:
            raise ComputeError(
                label + "的实际文件不可读，请检查文件是否存在、完整并可读取"
            ) from exc
        missing = required - set(info.get("fields", []))
        if missing:
            raise ComputeError(label + "缺少必要字段：" + "、".join(sorted(missing)))
        if kind == "vector":
            geometry_types = set(info.get("geometryTypes", []))
            if not geometry_types or not geometry_types <= {"Polygon", "MultiPolygon"}:
                raise ComputeError(
                    label
                    + "仅支持面几何（Polygon/MultiPolygon），实际为："
                    + "、".join(sorted(geometry_types or {"未知"}))
                )
            try:
                if not info.get("crs"):
                    raise ValueError("missing CRS")
                CRS.from_user_input(info["crs"])
            except (CRSError, ValueError, TypeError) as exc:
                raise ComputeError(
                    label + "缺少有效坐标系，请先为原始文件补充正确坐标系"
                ) from exc
        metadata[role] = info
    return metadata
