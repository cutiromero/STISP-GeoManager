"""Bounded, real map metadata and categories; all physical sources stay read-only."""

from contextlib import closing
import math
import sqlite3
import time

import numpy as np
from django.core.exceptions import PermissionDenied, ValidationError

from apps.catalog.data_query import get_resource_profile
from apps.core.permissions import has_feature_perm
from apps.core.storage import raster_processed_path, vector_geopackage_path
from apps.raster.models import RasterDataset
from .color_library import policy_revision, reference_entries

MAX_CLASSES = 96
MAX_CLASSIFICATION_PIXELS = 4_000_000
QUERY_SECONDS = 5


def require_map_read(user, resource):
    feature = {
        "vector": "core.load_vector_layer",
        "raster": "core.load_raster_layer",
    }.get(resource.data_type)
    if not feature:
        raise ValidationError("地图展示仅支持已登记矢量或栅格数据")
    if not has_feature_perm(user, feature):
        raise PermissionDenied("当前账号没有加载该类地图图层的权限")


def category_value(value):
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return str(int(value))
    return str(value)


def vector_categories(resource, field):
    def quote(value):
        return '"' + value.replace('"', '""') + '"'

    started = time.monotonic()
    try:
        with closing(
            sqlite3.connect(vector_geopackage_path().as_uri() + "?mode=ro", uri=True)
        ) as db:
            db.set_progress_handler(
                lambda: int(time.monotonic() - started > QUERY_SECONDS), 1000
            )
            rows = db.execute(
                f"SELECT {quote(field)}, COUNT(*) FROM {quote(resource.storage_path)} "
                f"WHERE {quote(field)} IS NOT NULL GROUP BY {quote(field)} "
                f"ORDER BY CAST({quote(field)} AS TEXT) LIMIT ?",
                (MAX_CLASSES + 1,),
            ).fetchall()
    except sqlite3.OperationalError as exc:
        raise ValidationError("类别读取未完成，请选择低基数字段或单色展示") from exc
    values = {}
    for value, count in rows:
        key = category_value(value)
        values[key] = values.get(key, 0) + count
    return [
        {"value": key, "count": value} for key, value in sorted(values.items())
    ], len(rows) <= MAX_CLASSES


def raster_categories(dataset, band):
    import rasterio
    from apps.raster.services.categorical import categorical_class_entries

    with rasterio.open(
        raster_processed_path(dataset.processed_relative_path)
    ) as source:
        if source.width * source.height > MAX_CLASSIFICATION_PIXELS:
            return (
                [],
                False,
                "分类统计超过本工具的400万像元上限，可先沿用已登记显示方案",
            )
        if not np.issubdtype(np.dtype(source.dtypes[band - 1]), np.integer):
            return [], False, "连续型波段沿用已登记显示方案，颜色表仅适用于整数类别"
        counts = {}
        for _, window in source.block_windows(band):
            data = source.read(band, window=window, masked=True).compressed()
            values, sizes = np.unique(data, return_counts=True)
            for value, count in zip(values, sizes):
                key = str(int(value))
                counts[key] = counts.get(key, 0) + int(count)
            if len(counts) > MAX_CLASSES:
                return [], False, "类别超过96项，请沿用显示方案或先分类"
    declared = {
        str(item["value"]): item
        for item in categorical_class_entries(dataset.source_gdalinfo)
    }
    return (
        [
            {
                "value": key,
                "count": count,
                "label": str(declared.get(key, {}).get("label", key)),
                **(
                    {"suggestedColor": declared[key]["color"]}
                    if declared.get(key, {}).get("color")
                    else {}
                ),
            }
            for key, count in sorted(counts.items(), key=lambda pair: int(pair[0]))
        ],
        True,
        "",
    )


def map_profile(resource, args):
    profile = get_resource_profile(resource)
    result = {
        "resource": {
            "id": resource.id,
            "name": resource.name,
            "dataType": resource.data_type,
        },
        "sourceUpdatedAt": resource.updated_at.isoformat(),
        "metadataSource": "map_display_profile",
        "boundsCrs": "EPSG:4326",
        "geometryType": profile.geometry_type,
        "fields": profile.fields,
        "bounds": list(profile.bounds or []),
        "featureCount": profile.feature_count,
        "coordinateSystem": resource.coordinate_system,
        "categories": [],
        "categoriesComplete": False,
    }
    if resource.data_type == "vector":
        if args.get("band") is not None:
            raise ValidationError("矢量分类使用field，不使用band")
        if not profile.geometry_type:
            raise ValidationError("资料没有就绪的空间图层")
        fields = {item["name"] for item in profile.fields}
        field = args.get("field")
        if field is None:
            field = next(
                (
                    name
                    for name in ["name", "geo_sym", "class", "type", "category"]
                    if name in fields
                ),
                None,
            )
        if field is not None:
            if not isinstance(field, str) or field not in fields:
                raise ValidationError("分类字段必须来自该资料的真实字段")
            items, complete = vector_categories(resource, field)
            entries = reference_entries(field, [item["value"] for item in items])
            result.update(
                categoryField=field,
                categories=[
                    {
                        **item,
                        **(
                            {
                                "suggestedColor": entries[item["value"]]["color"],
                                "referenceId": entries[item["value"]]["id"],
                                "referenceSource": entries[item["value"]]["source"],
                                "colorLocked": True,
                            }
                            if item["value"] in entries
                            else {}
                        ),
                    }
                    for item in items
                ],
                categoriesComplete=complete,
                colorPolicy={
                    "revision": policy_revision(),
                    "binding": "platform",
                    "rules": "与逻辑推理共用配色规则；命中色表原样采用，保留原表同色类别；仅调整非色表色",
                },
            )
        result["availableStyles"] = ["default", "single"] + (
            ["reference", "unique"]
            if result["categoriesComplete"] and result["categories"]
            else []
        )
    else:
        if args.get("field") is not None:
            raise ValidationError("栅格分类使用band，不使用矢量字段")
        dataset = RasterDataset.objects.get(data_resource=resource, status="ready")
        band = args.get("band", 1)
        if type(band) is not int or not 1 <= band <= dataset.band_count:
            raise ValidationError("波段号超出该栅格的实际范围")
        items, complete, note = raster_categories(dataset, band)
        mineral = reference_entries("mineral", [resource.name]).get(resource.name)
        if (
            mineral
            and mineral["domain"] == "alteration"
            and {item["value"] for item in items} <= {"0", "1"}
        ):
            for item in items:
                if item["value"] == "1":
                    item.update(
                        label=mineral["name"],
                        labelSource="registered_resource_name",
                        suggestedColor=mineral["color"],
                    )
        raster = profile.raster or {}
        result.update(
            band=band,
            categories=items,
            categoriesComplete=complete,
            limitation=note,
            raster={
                key: raster.get(key)
                for key in [
                    "id",
                    "mapLayerId",
                    "rasterKind",
                    "metadata",
                    "defaultRules",
                ]
            },
            availableStyles=["default"] + (["unique"] if complete and items else []),
        )
    return result


def cached_profile(run, resource, args, *, categories_required=False):
    for item in reversed(run.evidence):
        result = item.get("result", {})
        if (
            item.get("tool") != "get_map_data_profile"
            or item.get("resourceId") != resource.id
        ):
            continue
        if result.get("sourceUpdatedAt") != resource.updated_at.isoformat():
            continue
        if args.get("field") and args["field"] != result.get("categoryField"):
            continue
        if args.get("band", 1) != result.get("band", 1):
            continue
        return result
    if categories_required:
        raise ValidationError(
            "分类配色前先调用get_map_data_profile，核对真实字段和完整类别"
        )
    # Default display needs only metadata; category reads remain explicit.
    profile = get_resource_profile(resource)
    return {
        "sourceUpdatedAt": resource.updated_at.isoformat(),
        "geometryType": profile.geometry_type,
        "fields": profile.fields,
        "bounds": list(profile.bounds or []),
        "raster": profile.raster or {},
    }
