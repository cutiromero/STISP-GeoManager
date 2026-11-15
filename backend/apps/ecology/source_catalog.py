"""Metadata-only, live-authorized monitoring inputs and observation periods."""

from collections import defaultdict
import hashlib
import json
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q, Min, Max
from django.db.models.functions import ExtractYear

from apps.catalog.models import DataResource, ResourceObservationTimePoint
from apps.catalog.monitoring_metadata import (
    serialize_metadata,
    can_edit_visible_resource,
    editing_scope,
)
from apps.catalog.permissions import filter_accessible
from apps.catalog.serializers import serialize_resource
from apps.compute.models import AlgorithmVersion
from apps.projects.context import selected_project_id, require_live_membership
from apps.projects.models import Project
from .monitoring import configured_scenes

# CONFIGURATION
MAX_SOURCE_PAGE = 200
MAX_TIME_PAGE = 500
SCENE_FLOW_CODES = {
    "spartina": "spartina-distribution",
    "wildfire": "wildfire-history-observation",
    "landcover": "huanjiang-landcover",
}


def require_scene(scene):
    require_live_membership()
    project = Project.objects.get(pk=selected_project_id(), is_active=True)
    if scene not in SCENE_FLOW_CODES or scene not in configured_scenes(project):
        raise PermissionDenied("当前项目尚未开启该监测场景")
    return project


def source_query(user, scene):
    return (
        filter_accessible(
            DataResource.objects.filter(
                status="active",
                monitoring_usages__scene=scene,
                monitoring_usages__purpose="input",
            ),
            user,
        )
        .select_related(
            "observation_metadata", "inventory_group", "category", "category__parent"
        )
        .prefetch_related("monitoring_usages", "access_groups")
        .distinct()
    )


def method_for_scene(scene):
    from apps.business_flows.scopes import available_flows

    flow = (
        available_flows()
        .filter(code=SCENE_FLOW_CODES[scene], is_active=True)
        .select_related("current_version")
        .first()
    )
    if (
        not flow
        or not flow.current_version
        or flow.current_version.status != "published"
    ):
        return None
    operator = next(
        (
            row
            for row in flow.current_version.definition["nodes"]
            if row.get("algorithmVersionId")
        ),
        None,
    )
    if operator is None:
        return None
    version = (
        AlgorithmVersion.objects.select_related("algorithm")
        .filter(
            pk=operator["algorithmVersionId"],
            status="published",
            algorithm__enabled=True,
        )
        .first()
    )
    if version is None:
        return None
    manifest = version.manifest
    inputs = [
        {
            "key": row["key"],
            "label": row["label"],
            "kind": row["kind"],
            "required": row.get("required", True),
            "bandCount": (row.get("raster") or {}).get("bandCount"),
            "minBands": row.get("minBands", 0),
            "dtypes": (row.get("raster") or {}).get("dtypes", []),
            "nativeCube": bool((row.get("raster") or {}).get("cube")),
        }
        for row in manifest["inputs"]
    ]
    return {
        "definitionId": flow.pk,
        "versionId": flow.current_version_id,
        "operatorVersionId": version.pk,
        "title": flow.name,
        "goal": flow.description,
        "inputs": inputs,
        "parameters": manifest["parameters"],
        "inputRequirements": flow.current_version.definition["inputRequirements"],
    }


def _grid_key(schema):
    transform = schema.get("geoTransform", [])
    pixel, alignment = [], []
    if len(transform) == 6 and transform[1] and transform[5]:
        pixel = [transform[index] for index in (1, 2, 4, 5)]
        alignment = [
            round((transform[origin] / abs(transform[step])) % 1, 6) % 1
            for origin, step in [(0, 1), (3, 5)]
        ]
    return json.dumps(
        {"crs": schema.get("coordinateSystem"), "pixel": pixel, "alignment": alignment},
        sort_keys=True,
    )


def _compatible(schema, port):
    if schema.get("kind") != port["kind"] or port.get("nativeCube"):
        return False
    count = schema.get("bands", 0)
    if port.get("bandCount") is not None and count != port["bandCount"]:
        return False
    if count < port.get("minBands", 0):
        return False
    allowed = port.get("dtypes", [])
    return not allowed or all(
        kind.lower() in allowed for kind in schema.get("bandTypes", [])
    )


def input_sets(assets, method, scene):
    if not method:
        return []
    ports = [row for row in method["inputs"] if row["required"]]
    if not ports or any(port.get("nativeCube") for port in ports):
        return []
    groups = defaultdict(list)
    count = len(ports)
    for asset in assets:
        metadata = asset["metadata"]
        schema = metadata["sourceSchema"]
        if not any(_compatible(schema, port) for port in ports):
            continue
        period = metadata["period"]
        if count > 1 and (not period or not period["startsAt"]):
            continue
        groups[(metadata["collectionKey"], _grid_key(schema))].append(asset)
    result = []
    for (collection, _), members in groups.items():
        members.sort(
            key=lambda item: (
                (item["metadata"]["period"] or {}).get("startsAt") or "",
                item["resource"]["id"],
            )
        )
        by_period = {}
        for member in members:
            period = member["metadata"]["period"] or {}
            key = (
                period.get("startsAt"),
                period.get("endsAt"),
                member["resource"]["id"] if not period.get("startsAt") else None,
            )
            by_period[key] = member
        members = list(by_period.values())
        for end in range(count, len(members) + 1):
            selected = members[end - count : end]
            if not all(
                _compatible(asset["metadata"]["sourceSchema"], port)
                for port, asset in zip(ports, selected)
            ):
                continue
            inputs = {
                port["key"]: asset["resource"]["id"]
                for port, asset in zip(ports, selected)
            }
            epochs = [asset["metadata"]["resourceVersion"] for asset in selected]
            token = hashlib.sha256(
                json.dumps(
                    {"flow": method["versionId"], "inputs": inputs, "versions": epochs},
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            periods = [
                asset["metadata"]["period"]
                or {"startsAt": None, "endsAt": None, "precision": "unknown"}
                for asset in selected
            ]
            labels = []
            for asset, period in zip(selected, periods):
                labels.append(
                    period["startsAt"][:7]
                    if period["precision"] == "month"
                    else period["startsAt"] or asset["resource"]["name"]
                )
            result.append(
                {
                    "id": token,
                    "collectionKey": collection,
                    "label": " / ".join(labels),
                    "startsAt": periods[0]["startsAt"],
                    "endsAt": periods[-1]["endsAt"],
                    "inputs": inputs,
                    "periods": periods,
                    "resources": [asset["resource"] for asset in selected],
                }
            )
    return sorted(result, key=lambda item: item["endsAt"] or "", reverse=True)


def monitoring_sources(user, scene, *, offset=0, collection=None, year=None):
    require_scene(scene)
    if offset < 0 or offset > 100000 or (year is not None and not 1 <= year <= 9999):
        raise ValidationError("资料分页或年份无效")
    query = source_query(user, scene)
    collections = list(
        query.values(
            "observation_metadata__collection_key", "inventory_group__name"
        ).annotate(
            count=Count("pk"),
            startsAt=Min("observation_metadata__starts_at"),
            endsAt=Max("observation_metadata__ends_at"),
        )
    )
    if collection:
        query = query.filter(observation_metadata__collection_key=collection)
    if year:
        from datetime import date

        query = query.filter(
            Q(
                observation_metadata__starts_at__lte=date(year, 12, 31),
                observation_metadata__ends_at__gte=date(year, 1, 1),
            )
            | Q(observation_metadata__starts_at__isnull=True)
        )
    resources = list(
        query.order_by("-observation_metadata__ends_at", "-id")[
            offset : offset + MAX_SOURCE_PAGE + 1
        ]
    )
    more = len(resources) > MAX_SOURCE_PAGE
    resources = resources[:MAX_SOURCE_PAGE]
    native_ids = [
        row.observation_metadata.pk
        for row in resources
        if getattr(row, "observation_metadata", None)
        and row.observation_metadata.family == "seasfire"
    ]
    year_map = defaultdict(dict)
    if native_ids:
        for row in (
            ResourceObservationTimePoint.objects.filter(observation_id__in=native_ids)
            .annotate(year=ExtractYear("starts_at"))
            .values("observation_id", "year", "available_products")
            .annotate(count=Count("pk"))
        ):
            record = year_map[row["observation_id"]].setdefault(
                row["year"], {"year": row["year"], "count": 0, "validProducts": set()}
            )
            record["count"] += row["count"]
            record["validProducts"].update(row["available_products"])
    assets = []
    editor = editing_scope(user)
    for resource in resources:
        observation = getattr(resource, "observation_metadata", None)
        metadata = serialize_metadata(
            resource,
            observation,
            list(resource.monitoring_usages.all()),
            editable=can_edit_visible_resource(user, resource, editor),
        )
        years = []
        if observation and observation.family == "seasfire":
            years = [
                {**value, "validProducts": sorted(value["validProducts"])}
                for key, value in sorted(year_map[observation.pk].items())
            ]
        assets.append(
            {
                "resource": serialize_resource(resource),
                "metadata": metadata,
                "years": years,
                "collectionLabel": resource.inventory_group.name
                if resource.inventory_group
                else resource.name,
            }
        )
    method = method_for_scene(scene)
    return {
        "projectId": selected_project_id(),
        "scene": scene,
        "assets": assets,
        "method": method,
        "inputSets": input_sets(assets, method, scene),
        "hasMoreSources": more,
        "nextOffset": offset + MAX_SOURCE_PAGE if more else None,
        "collections": [
            {
                "key": row["observation_metadata__collection_key"] or "",
                "label": row["inventory_group__name"]
                or row["observation_metadata__collection_key"]
                or "资料集合",
                "count": row["count"],
                "startsAt": row["startsAt"].isoformat() if row["startsAt"] else None,
                "endsAt": row["endsAt"].isoformat() if row["endsAt"] else None,
            }
            for row in collections
        ],
    }


def source_times(
    user, scene, resource_id, year, product=None, after=None, limit=MAX_TIME_PAGE
):
    require_scene(scene)
    resource = source_query(user, scene).filter(pk=resource_id).first()
    if not resource:
        raise PermissionDenied("资料不存在或当前无权使用")
    observation = getattr(resource, "observation_metadata", None)
    if not observation:
        return {
            "resourceId": resource.pk,
            "indexVersion": "",
            "items": [],
            "nextOrdinal": None,
        }
    if not 1 <= limit <= MAX_TIME_PAGE or not 1 <= year <= 9999:
        raise ValidationError("日期分页范围无效")
    if product and product not in {"gwis_ba", "gfed_ba", "fcci_ba", "cams_frpfire"}:
        raise ValidationError("观测产品无效")
    query = observation.time_points.filter(starts_at__year=year)
    if after is not None:
        query = query.filter(ordinal__gt=after)
    rows = list(query.order_by("ordinal")[: limit + 1])
    more = len(rows) > limit
    rows = rows[:limit]
    # Product validity is kept from the source masks. Pagination advances on raw
    # ordinals even when a product has no available observations in that year.
    return {
        "resourceId": resource.pk,
        "indexVersion": observation.index_version,
        "items": [
            {
                "id": row.pk,
                "ordinal": row.ordinal,
                "date": row.starts_at.isoformat(),
                "endDate": row.ends_at.isoformat(),
                "validProducts": row.available_products,
            }
            for row in rows
            if not product or product in row.available_products
        ],
        "nextOrdinal": rows[-1].ordinal if more and rows else None,
    }
