"""Prepare personal, query-backed maps with bounded, display-only changes."""

import hashlib
import json
import math
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.audit.service import log_operation
from apps.catalog.models import WorkspaceScene
from apps.catalog.serializers import serialize_resource
from apps.core.permissions import has_feature_perm
from .map_profiles import cached_profile, map_profile, require_map_read
from .map_styles import display_style
from .platform_actions import PAGES
from .resource_discovery import resolve_discoverable_resource

MAX_LAYERS = 5
MAX_SNAPSHOT_BYTES = 512 * 1024


def scope_resources(run, user, policy, ids):
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= MAX_LAYERS
        or any(type(value) is not int or value <= 0 for value in ids)
        or len(ids) != len(set(ids))
    ):
        raise ValidationError("resourceIds须为1至5个不重复的已登记资源整数编号")
    touched = {
        item["resourceId"]
        for item in run.evidence
        if item.get("resourceId") is not None
        and item.get("tool") not in {"search_resources", "present_resource_catalog"}
    }
    if policy["maxResources"] > 0 and len(touched | set(ids)) > policy["maxResources"]:
        raise ValidationError("已超过本轮允许读取的资源数，请缩小地图范围")
    if not policy["allowCompare"] and len(touched | set(ids)) > 1:
        raise PermissionDenied("跨资源读取已关闭")
    result = []
    for identity in ids:
        resource = resolve_discoverable_resource(
            user, policy, identity, run.resource_ids
        )
        require_map_read(user, resource)
        result.append(resource)
    return result


def require_features(user, styles):
    for feature in ["catalog.add_workspacescene", "catalog.view_workspacescene"] + (
        ["core.custom_symbolization"] if styles else []
    ):
        if not has_feature_perm(user, feature):
            raise PermissionDenied("当前账号没有保存个人地图或自定义配色的权限")


def group_for(run, resource, profile, style):
    source = serialize_resource(resource)
    for key in ["description", "qualityNote"]:
        source[key] = source[key][:1000]
    identity = f"agent-{run.id}-{resource.id}"
    layer = {
        "id": identity + "-layer",
        "name": resource.name,
        "sourceResource": source,
        "geometryType": profile["geometryType"],
        "visible": True,
        "summary": "智能体准备的展示图层",
        "metadata": {"配色作用范围": "本工程", "原始数据": "未修改"},
        "fields": profile["fields"],
    }
    if resource.data_type == "vector":
        layer.update(
            layerType="vector",
            query={"attributeFilters": [], "spatialFilter": None},
            symbolization=style or {},
        )
    else:
        raster = profile["raster"]
        if not raster.get("id"):
            raise ValidationError("该栅格尚无就绪的地图数据集")
        rules = style or raster.get("defaultRules") or {}
        layer.update(
            layerType="raster",
            rasterDatasetId=raster["id"],
            rasterLayerId=raster.get("mapLayerId"),
            rasterKind="categorical"
            if rules.get("mode") == "unique"
            else raster.get("rasterKind"),
            rasterMetadata=raster.get("metadata"),
            symbolization=rules,
            rasterRulesMode="custom" if style else "default",
            renderStatus="queued",
            renderProgress=0,
            renderMessages=[],
        )
    return {
        "id": identity,
        "name": resource.name,
        "sourceResource": source,
        "visible": True,
        "summary": "个人展示，原始数据保持不变",
        "metadata": {},
        "symbolization": {"opacity": 100},
        "children": [layer],
    }


def map_view(profiles):
    bounds = [item.get("bounds") for item in profiles]
    bounds = [
        value
        for value in bounds
        if isinstance(value, list)
        and len(value) == 4
        and all(type(x) in {int, float} and math.isfinite(x) for x in value)
    ]
    if not bounds:
        return None
    west = min(value[0] for value in bounds)
    south = min(value[1] for value in bounds)
    east = max(value[2] for value in bounds)
    north = max(value[3] for value in bounds)
    span = max(east - west, (north - south) * 1.5, 0.001)
    return {
        "center": [(west + east) / 2, (south + north) / 2],
        "zoom": max(2, min(14, math.log2(360 / span) + 0.5)),
        "bearing": 0,
        "pitch": 0,
    }


def execute_map(run, user, policy, name, args):
    if run.conversation.mode != "agent":
        raise PermissionDenied("平台展示工具仅在科研智能体中开放")
    if name == "get_platform_link":
        page = args.get("page")
        if page not in PAGES:
            raise ValidationError("page仅支持map/resources/compute/knowledge")
        result = {
            "page": page,
            "title": PAGES[page][0],
            "projectId": run.project_tag_id,
            "url": PAGES[page][1] + f"?projectTagId={run.project_tag_id}",
        }
        return result, [(None, result)]
    if name == "get_map_data_profile":
        resource = scope_resources(run, user, policy, [args.get("resourceId")])[0]
        result = map_profile(resource, args)
        if len(json.dumps(result, ensure_ascii=False).encode()) > 24000:
            raise ValidationError("地图资料字段过宽，请选择更具体的资料")
        return result, [(resource, result)]
    if not policy.get("mapDisplayEnabled", True):
        raise PermissionDenied("管理员已关闭智能体地图展示工具")
    resources = scope_resources(run, user, policy, args.get("resourceIds"))
    specifications = args.get("styles", [])
    if not isinstance(specifications, list) or len(specifications) > len(resources):
        raise ValidationError("styles须为resourceIds中各图层的展示样式数组")
    if any(not isinstance(style, dict) for style in specifications):
        raise ValidationError("styles的每项须为图层配置对象")
    require_features(
        user,
        [
            style
            for style in specifications
            if style.get("mode", "default") != "default"
        ],
    )
    styles = {}
    for style in specifications:
        if (
            not isinstance(style, dict)
            or type(style.get("resourceId")) is not int
            or style["resourceId"] not in args["resourceIds"]
            or style["resourceId"] in styles
        ):
            raise ValidationError("每项样式须唯一对应本次地图中的resourceId")
        styles[style["resourceId"]] = style
    title = args.get("name", "智能体数据地图")
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise ValidationError("地图名称须为1至120字")
    profiles = []
    groups = []
    summaries = []
    for resource in resources:
        spec = styles.get(resource.id, {"resourceId": resource.id, "mode": "default"})
        profile = cached_profile(
            run, resource, spec, categories_required=spec.get("mode") == "unique"
        )
        style = display_style(resource, profile, spec)
        profiles.append(profile)
        groups.append(group_for(run, resource, profile, style))
        summaries.append(
            {
                "resourceId": resource.id,
                "name": resource.name,
                "mode": spec.get("mode", "default"),
                "classCount": len(spec.get("classes", [])),
            }
        )
    revision = [
        {"id": resource.id, "updatedAt": resource.updated_at.isoformat()}
        for resource in resources
    ]
    operation = hashlib.sha256(
        json.dumps([title.strip(), groups], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    snapshot = {
        "version": 2,
        "groups": groups,
        "selectedLayerId": groups[0]["children"][0]["id"],
        "mapView": map_view(profiles),
        "savedAt": timezone.now().isoformat(),
        "agentSource": {
            "runId": str(run.id),
            "operationHash": operation,
            "resources": revision,
        },
    }
    if len(json.dumps(snapshot, ensure_ascii=False).encode()) > MAX_SNAPSHOT_BYTES:
        raise ValidationError("地图配置超过512KiB，请减少图层或类别")
    with transaction.atomic():
        # Reserve SQLite's writer before any read/modify/write transaction snapshot.
        get_user_model().objects.filter(pk=user.id, is_active=True).update(
            last_login=F("last_login")
        )
        require_features(
            user,
            [
                style
                for style in specifications
                if style.get("mode", "default") != "default"
            ],
        )
        current = scope_resources(run, user, policy, args["resourceIds"])
        if revision != [
            {"id": value.id, "updatedAt": value.updated_at.isoformat()}
            for value in current
        ]:
            raise ValidationError("资料已更新，请重新读取地图概况后生成")
        scene = WorkspaceScene.objects.filter(
            owner=user,
            project_tag_id=run.project_tag_id,
            status="active",
            snapshot__agentSource__runId=str(run.id),
            snapshot__agentSource__operationHash=operation,
        ).first()
        if scene and scene.snapshot.get("groups") != groups:
            raise ValidationError("已生成的个人地图被修改，请换名称重新生成")
        if not scene:
            base = title.strip()
            label = base
            number = 2
            while WorkspaceScene.objects.filter(
                owner=user,
                project_tag_id=run.project_tag_id,
                kind="project",
                name=label,
            ).exists():
                label = f"{base}（{number}）"
                number += 1
            scene = WorkspaceScene.objects.create(
                owner=user,
                project_tag_id=run.project_tag_id,
                kind="project",
                name=label,
                description="智能体准备的个人展示工程；仅保存数据引用、查询与配色。",
                snapshot=snapshot,
            )
            log_operation(
                user,
                "agent",
                "prepare_map_workspace",
                "success",
                scene.name,
                target_type="workspace_scene",
                target_id=scene.id,
            )
    result = {
        "workspaceId": scene.id,
        "workspaceName": scene.name,
        "projectId": run.project_tag_id,
        "url": f"/map?sceneId={scene.id}&projectTagId={run.project_tag_id}",
        "layers": summaries,
        "originalDataChanged": False,
        "sharedWithOthers": False,
        "message": "个人地图已准备，可通过按钮加载；原始属性与几何保持不变",
    }
    return result, [(resource, result) for resource in resources]
