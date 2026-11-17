"""Personal reference workspaces; original research files remain read-only."""

from copy import deepcopy
import hashlib
import json

from django.core.exceptions import ObjectDoesNotExist, ValidationError

from apps.audit.service import log_operation
from apps.catalog.models import WorkspaceScene
from apps.catalog.share_access import check_snapshot
from apps.catalog.workspace_commands import save_revision
from apps.compute.input_versions import source_version
from apps.compute.packages import ComputeError
from apps.raster.models import RasterDataset
from .map_tools import MAX_LAYERS, scope_resources
from .map_profiles import cached_profile
from .map_styles import display_style


def nodes(snapshot):
    found = []

    def walk(value, depth=0):
        if depth > 20:
            raise ComputeError("工程结构过深")
        if isinstance(value, dict):
            if isinstance(value.get("id"), str) and (
                "children" in value or value.get("layerType") in {"vector", "raster"}
            ):
                found.append(value)
            for child in value.get("children", []):
                walk(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                walk(child, depth + 1)

    walk(snapshot.get("groups", []))
    return found


def context(run, user, policy, identity):
    scene = WorkspaceScene.objects.filter(
        pk=identity, owner=user, status="active", kind="project"
    ).first()
    if scene is None:
        raise ComputeError("个人工程不存在或无权访问", 404)
    check_snapshot(scene.snapshot, user, run.project_tag_id)
    layers = [
        node
        for node in nodes(scene.snapshot)
        if node.get("layerType") in {"vector", "raster"}
    ]
    if not 1 <= len(layers) <= MAX_LAYERS:
        raise ComputeError(
            "Agent个人工程操作须包含1至5个矢量或栅格图层，请拆分工程后操作"
        )
    identities = []
    for layer in layers:
        source = layer.get("sourceResource", {})
        resource_id = source.get("id") if isinstance(source, dict) else None
        if layer["layerType"] == "raster":
            dataset = RasterDataset.objects.filter(
                pk=layer.get("rasterDatasetId"), status="ready"
            ).first()
            if dataset is None or dataset.data_resource_id is None:
                raise ComputeError("工程栅格来源尚不可用")
            if resource_id is not None and resource_id != dataset.data_resource_id:
                raise ComputeError("工程栅格与资料引用不一致")
            resource_id = dataset.data_resource_id
        if type(resource_id) is not int or resource_id <= 0:
            raise ComputeError("工程图层缺少真实资料引用")
        identities.append(resource_id)
    resources = scope_resources(run, user, policy, list(dict.fromkeys(identities)))
    from apps.compute.cube_inputs import is_native_cube

    if any(is_native_cube(resource) for resource in resources):
        raise ComputeError(
            "原始数据立方体请先按真实时相生成观测成果，再操作个人地图工程"
        )
    by_id = {resource.pk: resource for resource in resources}
    return (
        scene,
        [(layer, by_id[identity]) for layer, identity in zip(layers, identities)],
        resources,
    )


def versions(resources):
    result = []
    for resource in sorted(resources, key=lambda item: item.pk):
        try:
            value = source_version(resource)
            available = True
        except (ComputeError, OSError, ValueError, ObjectDoesNotExist):
            value = {
                "unavailable": True,
                "resource": resource.pk,
                "revision": resource.updated_at.isoformat(),
            }
            available = False
        digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        result.append(
            {
                "resourceId": resource.pk,
                "updatedAt": resource.updated_at.isoformat(),
                "versionKey": digest,
                "available": available,
            }
        )
    return result


def summary(scene):
    return {
        "workspaceId": scene.pk,
        "projectId": scene.project_tag_id,
        "name": scene.name,
        "description": scene.description[:2000],
        "updatedAt": scene.updated_at.isoformat(),
    }


def detail(scene, layers, resources, layer_id=None):
    result = {
        **summary(scene),
        "sourceVersions": versions(resources),
        "nodes": [
            {
                "id": node["id"],
                "name": str(node.get("name", ""))[:160],
                "visible": bool(node.get("visible", True)),
            }
            for node in nodes(scene.snapshot)
        ],
        "layers": [],
    }
    if layer_id is not None and layer_id not in {layer["id"] for layer, _ in layers}:
        raise ComputeError("指定图层不属于该工程")
    for layer, resource in layers:
        item = {
            "id": layer["id"],
            "resourceId": resource.pk,
            "name": str(layer.get("name", resource.name))[:160],
            "layerType": layer["layerType"],
            "visible": bool(layer.get("visible", True)),
        }
        if layer_id == layer["id"]:
            item["symbolization"] = layer.get("symbolization", {})
        result["layers"].append(item)
    if len(json.dumps(result, ensure_ascii=False).encode()) > 24000:
        raise ComputeError("工程样式说明超过读取预算，请分图层核对资料概况")
    return result


def execute_workspace(run, user, policy, name, args):
    if name == "list_map_workspaces":
        query = WorkspaceScene.objects.filter(
            owner=user,
            status="active",
            kind="project",
            name__icontains=args.get("query", ""),
        ).order_by("id")
        offset, limit = args.get("offset", 0), args.get("limit", 10)
        total = query.count()
        result = {
            "items": [
                summary(scene)
                for scene in query.defer("snapshot")[offset : offset + limit]
            ],
            "total": total,
            "nextOffset": offset + limit if offset + limit < total else None,
        }
        return result, [(None, result)]
    scene, layers, resources = context(run, user, policy, args["workspaceId"])
    if name == "update_map_workspace":
        snapshot = deepcopy(scene.snapshot)
        values = {
            key: args[key].strip() for key in ("name", "description") if key in args
        }
        if "name" in values and not values["name"]:
            raise ValidationError("工程名称不能为空")
        visibility = args.get("visibility", {})
        targets = {node["id"]: node for node in nodes(snapshot)}
        if set(visibility) - set(targets):
            raise ValidationError("可见性引用了不属于该工程的图层或分组")
        for identity, visible in visibility.items():
            targets[identity]["visible"] = visible
        styles = args.get("styles", [])
        if styles:
            from apps.core.permissions import has_feature_perm

            if not has_feature_perm(user, "core.custom_symbolization"):
                raise ComputeError("当前账号没有自定义符号化权限", 403)
        by_id = {resource.pk: resource for resource in resources}
        styled = set()
        for style in styles:
            identity = style.get("resourceId")
            if identity not in by_id or identity in styled:
                raise ValidationError("样式必须唯一对应当前工程的真实资料")
            styled.add(identity)
            resource = by_id[identity]
            profile = cached_profile(
                run,
                resource,
                style,
                categories_required=style.get("mode") in {"unique", "reference"},
            )
            for layer, bound in layers:
                if bound.pk != identity:
                    continue
                target = targets[layer["id"]]
                selected = {**style}
                if selected.get("mode", "default") != "default":
                    selected.setdefault(
                        "opacity", target.get("symbolization", {}).get("opacity", 100)
                    )
                advice = []
                chosen = display_style(resource, profile, selected, audit=advice)
                target["symbolization"] = chosen or (
                    profile.get("raster", {}).get("defaultRules") or {}
                )
                target["colorAdvice"] = {"classes": advice} if advice else {}
                if layer["layerType"] == "raster":
                    for key in (
                        "tileUrl",
                        "imageCoordinates",
                        "tileMinZoom",
                        "tileMaxZoom",
                        "tileSampling",
                    ):
                        target.pop(key, None)
                    target.update(
                        rasterRulesMode="custom" if chosen else "default",
                        renderStatus="queued",
                        renderProgress=0,
                        renderMessages=[],
                    )
                    target.get("metadata", {}).pop("样式哈希", None)
        if visibility or styles:
            values["snapshot"] = snapshot
        if not values:
            raise ValidationError("没有可更新的个人工程字段")
        before = {resource.pk: resource.updated_at for resource in resources}

        def precondition():
            from .models import AgentRun
            from .policy import fresh_user, require_access

            if not AgentRun.objects.filter(
                pk=run.pk, cancel_requested=False, status="running"
            ).exists():
                raise ComputeError("本轮已停止，工程未更新", 409)
            actor = fresh_user(user.pk)
            current_policy = require_access(actor, "agent", run.model)
            _, _, current = context(run, actor, current_policy, scene.pk)
            if before != {resource.pk: resource.updated_at for resource in current}:
                raise ComputeError("工程资料已更新，请重新读取", 409)

        save_revision(
            scene,
            args["expectedUpdatedAt"],
            values,
            user=user,
            precondition=precondition,
        )
        scene.refresh_from_db()
        log_operation(
            user,
            "工作台",
            "Agent更新个人工程",
            "success",
            target_type="workspace_scene",
            target_id=scene.pk,
            target_name=scene.name,
        )
        scene, layers, resources = context(run, user, policy, scene.pk)
    result = detail(scene, layers, resources, args.get("layerId"))
    return result, [
        (None, {"workspaceId": scene.pk}),
        *[
            (resource, {"workspaceId": scene.pk, "resourceId": resource.pk})
            for resource in resources
        ],
    ]
