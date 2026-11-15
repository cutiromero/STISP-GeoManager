"""Resource usage and observation intervals, independent of ingestion provenance."""

import calendar
from datetime import date
import hashlib
import json
import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.permissions import has_feature_perm
from apps.projects.context import selected_project_id, require_live_membership
from .models import (
    DataResource,
    ResourceMonitoringUsage,
    ResourceObservationMetadata,
    ResourceObservationTimePoint,
)
from .permissions import filter_accessible, user_can_access, user_can_bypass_owner_only

# CONFIGURATION
SCENES = {"spartina", "wildfire", "landcover"}
FAMILIES = {
    "raster",
    "rgb_imagery",
    "multitemporal_features",
    "seasfire",
    "result",
    "vector",
    "auxiliary",
}
MAX_TIME_POINTS = 100000
PROFILE_FIELDS = {
    "family",
    "collectionKey",
    "startsAt",
    "endsAt",
    "precision",
    "usages",
}


def readable_resource(user, identity):
    require_live_membership()
    return filter_accessible(
        DataResource.objects.filter(pk=identity, project_tag_id=selected_project_id()),
        user,
    ).first()


def editing_scope(user):
    allowed = bool(
        user.is_authenticated
        and user.is_active
        and has_feature_perm(user, "catalog.change_dataresource")
    )
    return allowed, user_can_bypass_owner_only(user) if allowed else False


def can_edit_visible_resource(user, resource, scope=None):
    allowed, administrator = editing_scope(user) if scope is None else scope
    return allowed and (resource.maintainer_id == user.pk or administrator)


def can_edit(user, resource):
    return user_can_access(resource, user) and can_edit_visible_resource(user, resource)


def _date(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValidationError("时相日期格式无效")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValidationError("时相日期格式无效") from error
    if parsed.isoformat() != value:
        raise ValidationError("时相日期应使用YYYY-MM-DD格式")
    return parsed


def validate_period(data):
    precision = data.get("precision", "unknown")
    if precision not in ResourceObservationMetadata.Precision.values:
        raise ValidationError("时相精度无效")
    begin, end = _date(data.get("startsAt")), _date(data.get("endsAt"))
    if precision == "unknown":
        if begin or end:
            raise ValidationError("请为已登记时间选择时相精度")
    elif begin is None or end is None or begin > end:
        raise ValidationError("请填写完整且有序的观测时段")
    elif precision == "day" and begin != end:
        raise ValidationError("日精度应对应一个观测日期")
    elif precision == "month" and (
        begin.day != 1 or end.day != calendar.monthrange(end.year, end.month)[1]
    ):
        raise ValidationError("月精度应保存该月的完整区间，不能代替精确采集日")
    elif precision == "year" and (
        begin != date(begin.year, 1, 1) or end != date(end.year, 12, 31)
    ):
        raise ValidationError("年精度应保存该年的完整区间")
    return precision, begin, end


def period_payload(observation):
    if observation is None:
        return None
    return {
        "startsAt": observation.starts_at.isoformat()
        if observation.starts_at
        else None,
        "endsAt": observation.ends_at.isoformat() if observation.ends_at else None,
        "precision": observation.precision,
    }


def serialize_metadata(resource, observation, usages, *, editable=False):
    return {
        "resourceId": resource.pk,
        "resourceVersion": resource.updated_at.isoformat(),
        "family": observation.family if observation else None,
        "collectionKey": observation.collection_key if observation else "",
        "period": period_payload(observation),
        "sourceSchema": observation.source_schema if observation else {},
        "indexVersion": observation.index_version if observation else "",
        "usages": [{"scene": row.scene, "purpose": row.purpose} for row in usages],
        "canEdit": editable,
    }


def metadata_batch(user, identities):
    resources = list(
        filter_accessible(DataResource.objects.filter(pk__in=identities), user)
        .select_related("observation_metadata")
        .prefetch_related("monitoring_usages")
    )
    editor = editing_scope(user)
    return [
        serialize_metadata(
            resource,
            getattr(resource, "observation_metadata", None),
            resource.monitoring_usages.all(),
            editable=can_edit_visible_resource(user, resource, editor),
        )
        for resource in resources
    ]


def _raster_schema(resource):
    from apps.raster.models import RasterDataset

    dataset = RasterDataset.objects.filter(
        data_resource=resource, status="ready"
    ).first()
    if dataset is None:
        return {}
    info = dataset.source_gdalinfo
    bands = info.get("bands", [])
    epsg = (info.get("stac") or {}).get("proj:epsg")
    original_crs = (
        (info.get("coordinateSystem") or {}).get("wkt")
        if isinstance(info.get("coordinateSystem"), dict)
        else info.get("coordinateSystem")
    )
    return {
        "kind": "raster",
        "bands": dataset.band_count,
        "size": info.get("size", []),
        "bounds": dataset.bounds_4326,
        "coordinateSystem": f"EPSG:{epsg}"
        if epsg
        else original_crs or resource.coordinate_system,
        "geoTransform": info.get("geoTransform", []),
        "bandTypes": [row.get("type") or "" for row in bands],
        "bandNames": [row.get("description") or "" for row in bands],
        "renderDatasetId": dataset.pk,
    }


def native_index(resource):
    from apps.compute.cube_inputs import cube_root
    from apps.compute.native_cube_reader import Cube, PRODUCTS

    cube = Cube(cube_root(resource))
    if len(cube.dates) > MAX_TIME_POINTS:
        raise ValidationError("时间坐标超过当前索引预算")
    masks = {}
    for key, policy in PRODUCTS.items():
        if key + "/.zarray" not in cube.metadata:
            continue
        if policy["mask"]:
            if policy["mask"] + "/.zarray" not in cube.metadata:
                continue
            values = cube.read(policy["mask"])
            if len(values) != len(cube.dates):
                raise ValidationError("有效期掩膜长度与时间轴不符")
            masks[key] = [bool(value == 1) for value in values]
        else:
            masks[key] = [True] * len(cube.dates)
    points = []
    for index, day in enumerate(cube.dates):
        begin, end = cube.period(index, "gwis_ba")
        points.append(
            {
                "ordinal": index,
                "startsAt": begin.isoformat(),
                "endsAt": end.isoformat(),
                "availableProducts": [
                    key for key, values in masks.items() if values[index]
                ],
            }
        )
    variables = []
    for key in cube.metadata:
        if not key.endswith("/.zarray"):
            continue
        name = key.removesuffix("/.zarray")
        attrs = cube.attrs(name)
        if attrs.get("_ARRAY_DIMENSIONS") not in [
            ["latitude", "longitude"],
            ["time", "latitude", "longitude"],
        ]:
            continue
        variables.append(
            {
                "key": name,
                "label": attrs.get("long_name") or name,
                "unit": attrs.get("units") or "",
                "dimensions": attrs["_ARRAY_DIMENSIONS"],
            }
        )
    schema = {
        "kind": "native_cube",
        "coordinateSystem": "EPSG:4326",
        "bounds": [
            float(cube.longitude[0] - 0.125),
            float(cube.latitude[-1] - 0.125),
            float(cube.longitude[-1] + 0.125),
            float(cube.latitude[0] + 0.125),
        ],
        "gridResolution": 0.25,
        "timeCount": len(points),
        "variables": variables,
    }
    digest = hashlib.sha256(
        json.dumps({"points": points, "schema": schema}, sort_keys=True).encode()
    ).hexdigest()
    return schema, points, digest


def update_metadata(user, resource, data, *, require_edit=True):
    if require_edit and not can_edit(user, resource):
        raise PermissionDenied("只有资料维护者或管理员可以修改资料用途与时相")
    if not isinstance(data, dict) or set(data) - PROFILE_FIELDS:
        raise ValidationError("资料用途与时相字段无效")
    explicit_period = any(key in data for key in ("startsAt", "endsAt", "precision"))
    existing = ResourceObservationMetadata.objects.filter(resource=resource).first()
    if existing:
        defaults = {
            **period_payload(existing),
            "family": existing.family,
            "collectionKey": existing.collection_key,
            "usages": list(resource.monitoring_usages.values("scene", "purpose")),
        }
        data = {**defaults, **data}
    elif not explicit_period and resource.data_date:
        data = {
            "startsAt": resource.data_date.isoformat(),
            "endsAt": resource.data_date.isoformat(),
            "precision": "day",
            **data,
        }
    if "family" in data:
        family = data["family"]
    elif resource.file_format.upper() == "ZARR":
        family = "seasfire"
    else:
        schema = _raster_schema(resource) if resource.data_type == "raster" else {}
        family = (
            "multitemporal_features"
            if schema.get("bands") == 16
            else "rgb_imagery"
            if schema.get("bands") == 3
            else "raster"
            if resource.data_type == "raster"
            else "vector"
            if resource.data_type == "vector"
            else "auxiliary"
        )
    collection = data.get(
        "collectionKey",
        f"inventory-{resource.inventory_group_id}"
        if resource.inventory_group_id
        else f"resource-{resource.pk}",
    )
    if (
        not isinstance(family, str)
        or family not in FAMILIES
        or not isinstance(collection, str)
        or (collection and not re.fullmatch("[a-zA-Z0-9_-]{1,80}", collection))
    ):
        raise ValidationError("资料族或集合标识无效")
    usages = data.get("usages", [])
    if not isinstance(usages, list) or len(usages) > len(SCENES):
        raise ValidationError("请选择有效的监测用途")
    usage_map = {}
    for entry in usages:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"scene", "purpose"}
            or not isinstance(entry.get("scene"), str)
            or entry.get("scene") not in SCENES
            or not isinstance(entry.get("purpose"), str)
            or entry.get("purpose") not in ResourceMonitoringUsage.Purpose.values
            or entry["scene"] in usage_map
        ):
            raise ValidationError("监测场景或资料用途无效")
        usage_map[entry["scene"]] = entry["purpose"]
    precision, begin, end = validate_period(data)
    points, index_version = [], ""
    if family == "seasfire":
        if resource.file_format.upper() != "ZARR" or resource.data_type != "raster":
            raise ValidationError("SeasFire资料族需要已登记原生Zarr")
        schema, points, index_version = native_index(resource)
        if (
            explicit_period
            and precision != "unknown"
            and (
                str(begin) != points[0]["startsAt"] or str(end) != points[-1]["endsAt"]
            )
        ):
            raise ValidationError("原生数据的观测时段由实际时间坐标确定")
        begin, end, precision = (
            _date(points[0]["startsAt"]),
            _date(points[-1]["endsAt"]),
            "interval",
        )
    else:
        schema = (
            _raster_schema(resource)
            if resource.data_type == "raster"
            else {"kind": resource.data_type}
        )
        if begin:
            points = [
                {
                    "ordinal": 0,
                    "startsAt": begin.isoformat(),
                    "endsAt": end.isoformat(),
                    "availableProducts": [],
                }
            ]
        index_version = hashlib.sha256(
            json.dumps(
                {"period": [str(begin), str(end), precision], "schema": schema},
                sort_keys=True,
            ).encode()
        ).hexdigest()
    with transaction.atomic():
        from django.db.models import F

        # Reserve the WAL writer before live authorization reads fix a snapshot.
        DataResource.objects.filter(pk=resource.pk).update(updated_at=F("updated_at"))
        require_live_membership()
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.get(pk=user.pk)
        if not user.is_active:
            raise PermissionDenied("当前账户已停用")
        fresh = DataResource.objects.select_for_update().get(
            pk=resource.pk, project_tag_id=selected_project_id()
        )
        if not user_can_access(fresh, user) or fresh.updated_at != resource.updated_at:
            raise PermissionDenied("资料或访问权限已变化，请刷新后重试")
        if require_edit and not can_edit(user, fresh):
            raise PermissionDenied("资料维护权限已变化")
        observation, created = ResourceObservationMetadata.objects.get_or_create(
            resource=fresh
        )
        old_usages = dict(
            ResourceMonitoringUsage.objects.filter(resource=fresh).values_list(
                "scene", "purpose"
            )
        )
        changed = (
            created
            or old_usages != usage_map
            or (
                observation.family,
                observation.collection_key,
                observation.starts_at,
                observation.ends_at,
                observation.precision,
                observation.source_schema,
                observation.index_version,
            )
            != (family, collection, begin, end, precision, schema, index_version)
        )
        if not changed:
            return serialize_metadata(
                fresh,
                observation,
                list(fresh.monitoring_usages.all()),
                editable=can_edit(user, fresh),
            )
        changed_index = observation.index_version != index_version
        observation.family, observation.collection_key = family, collection
        observation.starts_at, observation.ends_at, observation.precision = (
            begin,
            end,
            precision,
        )
        observation.source_schema, observation.index_version = schema, index_version
        observation.indexed_at = timezone.now()
        observation.save()
        if changed_index:
            observation.time_points.all().delete()
            ResourceObservationTimePoint.objects.bulk_create(
                [
                    ResourceObservationTimePoint(
                        observation=observation,
                        ordinal=point["ordinal"],
                        starts_at=_date(point["startsAt"]),
                        ends_at=_date(point["endsAt"]),
                        available_products=point["availableProducts"],
                        source_version=index_version,
                        project_tag_id=fresh.project_tag_id,
                    )
                    for point in points
                ],
                batch_size=500,
            )
        ResourceMonitoringUsage.objects.filter(resource=fresh).exclude(
            scene__in=usage_map
        ).delete()
        for scene, purpose in usage_map.items():
            ResourceMonitoringUsage.objects.update_or_create(
                resource=fresh,
                scene=scene,
                defaults={"purpose": purpose, "updated_by": user},
            )
        fresh.updated_at = timezone.now()
        fresh.save(update_fields=["updated_at"])
    return serialize_metadata(
        fresh,
        observation,
        list(fresh.monitoring_usages.all()),
        editable=can_edit(user, fresh),
    )
