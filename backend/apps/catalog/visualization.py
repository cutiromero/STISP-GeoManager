from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any

import numpy as np
import pandas as pd
from django.utils import timezone

from apps.catalog.data_query import get_resource_profile, read_vector_resource
from apps.catalog.models import DataResource
from apps.catalog.serializers import serialize_resource
from apps.catalog.symbolization_templates import recommended_symbolization_templates


MAX_CATEGORY_FIELDS = 6
MAX_NUMERIC_FIELDS = 8
LOW_CARDINALITY_LIMIT = 200

COORDINATE_FIELD_HINTS = (
    "经度",
    "纬度",
    "longitude",
    "latitude",
    "lng",
    "lat",
    "x坐标",
    "y坐标",
)
IDENTIFIER_FIELD_HINTS = (
    "id",
    "编号",
    "编码",
    "采集号",
    "sample_id",
    "sample",
    "code",
)
CATEGORY_PRIORITY_HINTS = (
    "性别",
    "采集地点",
    "采集单位",
    "地州",
    "地区",
    "市县",
    "乡镇",
    "地点",
    "栖息地",
    "物种",
    "种",
    "科",
    "属",
    "生活型",
    "分布方式",
    "health",
    "status",
)
NUMERIC_PRIORITY_HINTS = (
    "海拔",
    "altitude",
    "重要值",
    "密度",
    "盖度",
    "株数",
    "频度",
    "fric",
    "feve",
    "fdiv",
    "fdis",
    "raoq",
    "shannon",
    "simpson",
    "sr",
    "pielou",
    "pd",
    "ec",
    "ph",
    "swc",
    "soc",
    "agbc",
    "npp",
    "bio",
)


def resource_visualization_summary(
    resource: DataResource, *, top_n: int = 8, histogram_bins: int = 8
) -> dict[str, Any]:
    top_n = _clamp_int(top_n, 3, 20)
    histogram_bins = _clamp_int(histogram_bins, 4, 20)
    profile = get_resource_profile(resource)

    if resource.data_type == DataResource.DataType.VECTOR:
        return _vector_summary(resource, profile, top_n, histogram_bins)
    if resource.data_type == DataResource.DataType.RASTER:
        return _raster_summary(resource, profile)
    return _profile_only_summary(resource, profile)


def _vector_summary(
    resource: DataResource, profile: Any, top_n: int, histogram_bins: int
) -> dict[str, Any]:
    gdf = read_vector_resource(resource)
    geometry_name = (
        gdf.geometry.name if getattr(gdf, "geometry", None) is not None else "geometry"
    )
    field_names = [column for column in gdf.columns if column != geometry_name]
    field_descriptions = {
        field["name"]: field.get("description") or field["name"]
        for field in profile.fields
    }
    total = int(len(gdf))
    category_stats = _category_stats(gdf, field_names, field_descriptions, top_n)
    numeric_stats = _numeric_stats(
        gdf, field_names, field_descriptions, histogram_bins
    )
    spatial_summary = _spatial_summary(gdf, profile.bounds, total)
    quality_issues = _quality_issues(
        gdf,
        field_names,
        total,
        spatial_summary,
        category_stats,
        numeric_stats,
    )
    return {
        "resource": serialize_resource(resource),
        "domainType": resource.domain_type or "other",
        "generatedAt": _iso_now(),
        "source": "backend_aggregate",
        "profile": {
            "featureCount": profile.feature_count,
            "fieldCount": len(field_names),
            "geometryType": profile.geometry_type,
            "bounds": profile.bounds,
        },
        "categoryStats": category_stats,
        "numericStats": numeric_stats,
        "spatialSummary": spatial_summary,
        "qualityIssues": quality_issues,
        "recommendedCharts": _recommended_charts(
            resource.domain_type or "other", category_stats, numeric_stats, False
        ),
        "recommendedSymbolizations": recommended_symbolization_templates(
            resource.domain_type or "other", gdf, field_names
        ),
        "monitorPreview": _monitor_preview(),
    }


def _raster_summary(resource: DataResource, profile: Any) -> dict[str, Any]:
    raster = profile.raster or {}
    metadata = raster.get("metadata") or {}
    size = metadata.get("size") or []
    bands = metadata.get("bands") or []
    pixel_count = _pixel_count(size)
    numeric_stats = []
    for band in bands[:MAX_NUMERIC_FIELDS]:
        minimum = _finite_or_none(band.get("min"))
        maximum = _finite_or_none(band.get("max"))
        band_label = str(band.get("description") or f"Band {band.get('band')}")
        histogram = []
        if minimum is not None and maximum is not None:
            histogram.append(
                {
                    "min": minimum,
                    "max": maximum,
                    "count": pixel_count or 0,
                    "label": _range_label(minimum, maximum),
                }
            )
        numeric_stats.append(
            {
                "field": f"Band {band.get('band')}",
                "label": band_label,
                "count": pixel_count or 0,
                "nullCount": 0,
                "min": minimum,
                "max": maximum,
                "mean": None,
                "median": None,
                "q1": None,
                "q3": None,
                "histogram": histogram,
            }
        )
    category_stats = []
    if bands:
        category_stats.append(
            {
                "field": "bands",
                "label": "波段构成",
                "total": len(bands),
                "nullCount": 0,
                "uniqueCount": len(bands),
                "truncated": False,
                "items": [
                    {
                        "label": str(band.get("description") or f"Band {band.get('band')}"),
                        "count": 1,
                        "ratio": _ratio(1, len(bands)),
                    }
                    for band in bands[:12]
                ],
            }
        )
    spatial_summary = {
        "featureCount": None,
        "validGeometryCount": None,
        "nullGeometryCount": None,
        "coordinateCoverageRatio": None,
        "bounds": profile.bounds,
        "geometryTypes": [],
        "centroid": _bounds_centroid(profile.bounds),
    }
    quality_issues = _raster_quality_issues(raster, metadata, bands, profile.bounds)
    return {
        "resource": serialize_resource(resource),
        "domainType": resource.domain_type or "remote_sensing",
        "generatedAt": _iso_now(),
        "source": "raster_metadata",
        "profile": {
            "featureCount": None,
            "fieldCount": len(bands),
            "geometryType": "Raster",
            "bounds": profile.bounds,
        },
        "categoryStats": category_stats,
        "numericStats": numeric_stats,
        "spatialSummary": spatial_summary,
        "qualityIssues": quality_issues,
        "recommendedCharts": _recommended_charts(
            resource.domain_type or "remote_sensing", category_stats, numeric_stats, True
        ),
        "recommendedSymbolizations": [],
        "monitorPreview": _monitor_preview(),
    }


def _profile_only_summary(resource: DataResource, profile: Any) -> dict[str, Any]:
    return {
        "resource": serialize_resource(resource),
        "domainType": resource.domain_type or "other",
        "generatedAt": _iso_now(),
        "source": "profile_only",
        "profile": {
            "featureCount": profile.feature_count,
            "fieldCount": len(profile.fields),
            "geometryType": profile.geometry_type,
            "bounds": profile.bounds,
        },
        "categoryStats": [],
        "numericStats": [],
        "spatialSummary": {
            "featureCount": profile.feature_count,
            "validGeometryCount": None,
            "nullGeometryCount": None,
            "coordinateCoverageRatio": None,
            "bounds": profile.bounds,
            "geometryTypes": [],
            "centroid": _bounds_centroid(profile.bounds),
        },
        "qualityIssues": [
            {
                "code": "profile_only",
                "severity": "info",
                "title": "仅可读取资源元数据",
                "message": "当前资源暂不支持后端明细聚合，右侧面板将展示基础元数据。",
                "count": 0,
                "ratio": 0,
                "field": None,
            }
        ],
        "recommendedCharts": _recommended_charts(
            resource.domain_type or "other", [], [], False
        ),
        "recommendedSymbolizations": [],
        "monitorPreview": _monitor_preview(),
    }


def _category_stats(
    gdf, field_names: list[str], labels: dict[str, str], top_n: int
) -> list[dict[str, Any]]:
    candidates: list[tuple[int, dict[str, Any]]] = []
    for field in field_names:
        if _is_coordinate_field(field):
            continue
        series = gdf[field]
        total = int(len(series))
        non_null = series.dropna()
        if total == 0 or len(non_null) == 0:
            continue
        unique_count = int(non_null.astype(str).nunique(dropna=True))
        if unique_count == 0:
            continue
        numeric_ratio = _numeric_ratio(series)
        high_cardinality = unique_count > LOW_CARDINALITY_LIMIT and unique_count > total * 0.65
        if numeric_ratio >= 0.85 and not _has_hint(field, CATEGORY_PRIORITY_HINTS):
            continue
        if high_cardinality and not _has_hint(field, CATEGORY_PRIORITY_HINTS):
            continue
        counts = non_null.astype(str).replace("", "未填写").value_counts()
        items = [
            {
                "label": str(label),
                "count": int(count),
                "ratio": _ratio(int(count), total),
            }
            for label, count in counts.head(top_n).items()
        ]
        if not items:
            continue
        stat = {
            "field": field,
            "label": _field_label(field, labels),
            "total": total,
            "nullCount": int(series.isna().sum()),
            "uniqueCount": unique_count,
            "truncated": unique_count > len(items),
            "items": items,
        }
        candidates.append((_field_priority(field, CATEGORY_PRIORITY_HINTS), stat))
    candidates.sort(key=lambda item: item[0])
    return [stat for _, stat in candidates[:MAX_CATEGORY_FIELDS]]


def _numeric_stats(
    gdf, field_names: list[str], labels: dict[str, str], histogram_bins: int
) -> list[dict[str, Any]]:
    candidates: list[tuple[int, dict[str, Any]]] = []
    for field in field_names:
        if _is_coordinate_field(field) or _is_identifier_field(field):
            continue
        series = gdf[field]
        numeric = pd.to_numeric(series, errors="coerce")
        valid = numeric.dropna()
        if len(valid) == 0:
            continue
        if len(valid) / max(1, len(series.dropna())) < 0.85:
            continue
        minimum = _round_float(valid.min())
        maximum = _round_float(valid.max())
        stat = {
            "field": field,
            "label": _field_label(field, labels),
            "count": int(len(valid)),
            "nullCount": int(len(series) - len(valid)),
            "min": minimum,
            "max": maximum,
            "mean": _round_float(valid.mean()),
            "median": _round_float(valid.median()),
            "q1": _round_float(valid.quantile(0.25)),
            "q3": _round_float(valid.quantile(0.75)),
            "histogram": _histogram(valid, histogram_bins),
        }
        candidates.append((_field_priority(field, NUMERIC_PRIORITY_HINTS), stat))
    candidates.sort(key=lambda item: item[0])
    return [stat for _, stat in candidates[:MAX_NUMERIC_FIELDS]]


def _spatial_summary(gdf, bounds: list[float], total: int) -> dict[str, Any]:
    geometry = getattr(gdf, "geometry", None)
    if geometry is None:
        return {
            "featureCount": total,
            "validGeometryCount": None,
            "nullGeometryCount": None,
            "coordinateCoverageRatio": None,
            "bounds": bounds,
            "geometryTypes": [],
            "centroid": _bounds_centroid(bounds),
        }
    valid = geometry.notna() & ~geometry.is_empty
    valid_count = int(valid.sum())
    null_count = max(0, total - valid_count)
    type_counts = geometry[valid].geom_type.astype(str).value_counts()
    centroid = None
    if valid_count > 0:
        try:
            valid_geometry = geometry[valid]
            geometry_union = (
                valid_geometry.union_all()
                if hasattr(valid_geometry, "union_all")
                else valid_geometry.unary_union
            )
            centroid_geometry = geometry_union.centroid
            centroid = [
                _round_float(centroid_geometry.x),
                _round_float(centroid_geometry.y),
            ]
        except Exception:
            centroid = _bounds_centroid(bounds)
    return {
        "featureCount": total,
        "validGeometryCount": valid_count,
        "nullGeometryCount": null_count,
        "coordinateCoverageRatio": _ratio(valid_count, total),
        "bounds": bounds,
        "geometryTypes": [
            {"label": str(label), "count": int(count), "ratio": _ratio(int(count), total)}
            for label, count in type_counts.items()
        ],
        "centroid": centroid,
    }


def _quality_issues(
    gdf,
    field_names: list[str],
    total: int,
    spatial_summary: dict[str, Any],
    category_stats: list[dict[str, Any]],
    numeric_stats: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    null_geometry_count = spatial_summary.get("nullGeometryCount") or 0
    if null_geometry_count:
        issues.append(
            _issue(
                "null_geometry",
                "warning",
                "空几何记录",
                f"存在 {null_geometry_count} 条记录没有可用空间几何。",
                null_geometry_count,
                total,
            )
        )
    if total == 0:
        issues.append(
            _issue("empty_resource", "info", "暂无要素", "当前资源没有可聚合的空间记录。", 0, 0)
        )
    if not field_names:
        issues.append(
            _issue("no_fields", "warning", "缺少属性字段", "当前资源没有可用于图表分析的属性字段。", 0, total)
        )

    for field in field_names:
        series = gdf[field]
        null_count = int(series.isna().sum())
        if total > 0 and null_count / total >= 0.35:
            issues.append(
                _issue(
                    "high_null_ratio",
                    "warning",
                    "字段缺失率较高",
                    f"字段“{field}”空值占比较高，图表分析时建议复核。",
                    null_count,
                    total,
                    field,
                )
            )
            if len(issues) >= 6:
                break

    for field in field_names:
        if not _is_identifier_field(field):
            continue
        series = gdf[field].dropna().astype(str)
        if len(series) <= 1:
            continue
        duplicate_count = int(len(series) - series.nunique())
        if duplicate_count > 0:
            issues.append(
                _issue(
                    "duplicate_identifier",
                    "warning",
                    "编号存在重复",
                    f"字段“{field}”存在 {duplicate_count} 条重复编号记录。",
                    duplicate_count,
                    total,
                    field,
                )
            )
            break

    if not category_stats and not numeric_stats and total > 0:
        issues.append(
            _issue(
                "limited_visual_fields",
                "info",
                "可视化字段较少",
                "当前字段结构偏向明细或编号，建议完善分类字段或数值指标。",
                0,
                total,
            )
        )
    if not issues:
        issues.append(
            _issue(
                "quality_ready",
                "info",
                "基础质量良好",
                "当前资源字段、空间和数值结构可用于可视化分析。",
                0,
                total,
            )
        )
    return issues[:8]


def _raster_quality_issues(
    raster: dict[str, Any],
    metadata: dict[str, Any],
    bands: list[dict[str, Any]],
    bounds: list[float],
) -> list[dict[str, Any]]:
    issues = []
    status = raster.get("status")
    if status and status != "ready":
        issues.append(
            _issue(
                "raster_not_ready",
                "warning",
                "栅格尚未就绪",
                "该栅格数据集尚未完成预处理或渲染准备。",
                1,
                1,
            )
        )
    if not bounds:
        issues.append(
            _issue(
                "missing_raster_bounds",
                "warning",
                "缺少空间范围",
                "栅格元数据缺少 WGS84 空间范围，无法进行地图范围摘要。",
                1,
                1,
            )
        )
    if not bands:
        issues.append(
            _issue(
                "missing_raster_bands",
                "warning",
                "缺少波段信息",
                "栅格元数据缺少波段统计信息，无法绘制像元值范围图。",
                1,
                1,
            )
        )
    missing_min_max = [
        band
        for band in bands
        if _finite_or_none(band.get("min")) is None
        or _finite_or_none(band.get("max")) is None
    ]
    if missing_min_max:
        issues.append(
            _issue(
                "missing_band_range",
                "info",
                "波段范围不完整",
                "部分波段缺少最小值或最大值，直方图将仅展示可用范围。",
                len(missing_min_max),
                max(1, len(bands)),
            )
        )
    if not metadata.get("size"):
        issues.append(
            _issue(
                "missing_raster_size",
                "info",
                "缺少影像尺寸",
                "栅格元数据缺少像素尺寸，无法估算像元规模。",
                1,
                1,
            )
        )
    if not issues:
        issues.append(
            _issue(
                "raster_metadata_ready",
                "info",
                "栅格元数据可用",
                "当前栅格具备范围、波段和渲染摘要，可用于右侧影像洞察。",
                0,
                1,
            )
        )
    return issues


def _recommended_charts(
    domain_type: str,
    category_stats: list[dict[str, Any]],
    numeric_stats: list[dict[str, Any]],
    is_raster: bool,
) -> list[dict[str, Any]]:
    first_category = category_stats[0]["field"] if category_stats else ""
    first_numeric = numeric_stats[0]["field"] if numeric_stats else ""
    common = []
    if first_category:
        common.append(
            {
                "chartType": "donut",
                "title": "分类构成",
                "description": "展示当前资源主要分类字段的占比结构。",
                "fields": [first_category],
            }
        )
    if first_numeric:
        common.append(
            {
                "chartType": "histogram",
                "title": "数值分布",
                "description": "展示核心连续指标的分位和分布范围。",
                "fields": [first_numeric],
            }
        )
    domain_charts = {
        "germplasm": [
            ("donut", "性别结构", "展示雌株、雄株和未知样本占比。", ["性别"]),
            ("boxplot", "海拔分布", "展示采集点海拔差异。", ["海拔"]),
        ],
        "individual": [
            ("sunburst", "科属种谱系", "展示个体采集记录的分类层级结构。", ["科", "属", "种"]),
            ("rank_bar", "物种采集量", "展示高频物种记录。", ["物种中文名"]),
        ],
        "population": [
            ("rank_bar", "重要值排行", "展示种群优势度排序。", ["重要值"]),
            ("scatter", "密度-盖度关系", "展示密度、盖度之间的关系。", ["密度", "盖度"]),
        ],
        "community": [
            ("radar", "多样性画像", "展示功能多样性和物种多样性核心指标。", ["FRic", "Shannon", "Simpson", "SR"]),
            ("heatmap", "性状与环境矩阵", "展示群落性状、土壤和气候因子。", ["CWM", "bio"]),
        ],
        "field_survey": [
            ("stacked_bar", "调查构成", "展示样方、栖息地和调查分类结构。", ["栖息地类型", "样线"]),
            ("quality_list", "调查质量", "展示坐标、字段和编号质量检查。", []),
        ],
        "remote_sensing": [
            ("raster_preview", "影像元数据", "展示栅格范围、波段和色带摘要。", ["Band 1"]),
            ("histogram", "像元值范围", "展示波段最小值、最大值和可用范围。", ["Band 1"]),
        ],
    }
    charts = [
        {
            "chartType": chart_type,
            "title": title,
            "description": description,
            "fields": fields,
        }
        for chart_type, title, description, fields in domain_charts.get(domain_type, [])
    ]
    if is_raster and domain_type != "remote_sensing":
        charts.insert(
            0,
            {
                "chartType": "raster_preview",
                "title": "栅格摘要",
                "description": "展示栅格范围、波段和像元值范围。",
                "fields": ["Band 1"],
            },
        )
    merged = charts + common
    seen = set()
    result = []
    for chart in merged:
        key = (chart["chartType"], chart["title"])
        if key in seen:
            continue
        seen.add(key)
        result.append(chart)
    return result[:5]


def _monitor_preview() -> dict[str, Any]:
    return {
        "title": "监测能力预留",
        "status": "planned",
        "items": [
            {
                "label": "阈值配置",
                "status": "planned",
                "description": "后续支持按字段、数据类型和专题配置预警阈值。",
            },
            {
                "label": "定时扫描",
                "status": "planned",
                "description": "后续支持定期扫描数据质量、生态指标和栅格处理状态。",
            },
            {
                "label": "异常复核",
                "status": "planned",
                "description": "后续支持异常记录定位、确认、忽略和复核流程闭环。",
            },
        ],
    }


def _histogram(valid: pd.Series, bins: int) -> list[dict[str, Any]]:
    if len(valid) == 0:
        return []
    minimum = float(valid.min())
    maximum = float(valid.max())
    if not isfinite(minimum) or not isfinite(maximum):
        return []
    if minimum == maximum:
        value = _round_float(minimum)
        return [{"min": value, "max": value, "count": int(len(valid)), "label": str(value)}]
    counts, edges = np.histogram(valid.to_numpy(dtype=float), bins=bins)
    result = []
    for index, count in enumerate(counts):
        low = _round_float(edges[index])
        high = _round_float(edges[index + 1])
        result.append(
            {
                "min": low,
                "max": high,
                "count": int(count),
                "label": _range_label(low, high),
            }
        )
    return result


def _issue(
    code: str,
    severity: str,
    title: str,
    message: str,
    count: int,
    total: int,
    field: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "title": title,
        "message": message,
        "count": int(count),
        "ratio": _ratio(count, total) if total else 0,
        "field": field,
    }


def _numeric_ratio(series) -> float:
    non_null = series.dropna()
    if len(non_null) == 0:
        return 0
    numeric = pd.to_numeric(non_null, errors="coerce")
    return float(numeric.notna().sum() / len(non_null))


def _field_priority(field: str, hints: tuple[str, ...]) -> int:
    normalized = field.lower()
    for index, hint in enumerate(hints):
        if hint.lower() in normalized:
            return index
    return 1000


def _has_hint(field: str, hints: tuple[str, ...]) -> bool:
    normalized = field.lower()
    return any(hint.lower() in normalized for hint in hints)


def _is_coordinate_field(field: str) -> bool:
    return _has_hint(field, COORDINATE_FIELD_HINTS)


def _is_identifier_field(field: str) -> bool:
    return _has_hint(field, IDENTIFIER_FIELD_HINTS)


def _field_label(field: str, labels: dict[str, str]) -> str:
    label = labels.get(field) or field
    if len(label) > 24:
        return field
    return str(label)


def _ratio(count: int, total: int) -> float:
    if total <= 0:
        return 0
    return round(count / total, 4)


def _round_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(number):
        return None
    return round(number, 6)


def _finite_or_none(value: Any) -> float | None:
    return _round_float(value)


def _range_label(minimum: float, maximum: float) -> str:
    return f"{minimum:.2f}-{maximum:.2f}"


def _bounds_centroid(bounds: list[float]) -> list[float] | None:
    if len(bounds) != 4:
        return None
    west, south, east, north = bounds
    try:
        return [_round_float((float(west) + float(east)) / 2), _round_float((float(south) + float(north)) / 2)]
    except (TypeError, ValueError):
        return None


def _pixel_count(size: Any) -> int | None:
    if not isinstance(size, list) or len(size) < 2:
        return None
    try:
        width = int(size[0])
        height = int(size[1])
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return width * height


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _iso_now() -> str:
    now: datetime = timezone.now()
    return now.isoformat()
