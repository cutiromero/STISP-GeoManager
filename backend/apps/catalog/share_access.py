"""Live read checks for invitations; no project or private-resource grants."""

from contextlib import contextmanager

from apps.compute.access import permission, require_actor
from apps.compute.models import ComputeImport, ComputeOutput
from apps.compute.packages import ComputeError
from apps.core.initialization import is_guest_user
from apps.core.permissions import has_feature_perm
from apps.core.storage import app_path
from apps.projects.context import ProjectScope, is_superadmin, project_scope

from .models import (
    DataResource,
    MapComposition,
    MapCompositionVersion,
    ShareInvitation,
    WorkspaceScene,
)
from .permissions import user_can_access, user_has_full_data_access


@contextmanager
def actor_scope(user, project_id: int):
    with project_scope(
        ProjectScope((project_id,), project_id, user.id, is_superadmin(user))
    ):
        yield


def require_features(user, project_id: int, *features: str) -> None:
    require_actor(user, project_id)
    if is_guest_user(user):
        raise ComputeError("游客账号不能邀请分享", 403)
    with actor_scope(user, project_id):
        if any(not has_feature_perm(user, name) for name in features):
            raise ComputeError("账号缺少查看该对象所需的功能权限", 403)


def _resource(user, project_id: int, resource_id: int) -> None:
    item = DataResource._base_manager.filter(
        pk=resource_id, project_tag_id=project_id
    ).first()
    with actor_scope(user, project_id):
        if item is None or item.status != "active" or not user_can_access(item, user):
            raise ComputeError("底层数据不存在或账号没有读取权限，无法分享", 403)
        feature = {
            "raster": "core.load_raster_layer",
            "vector": "core.load_vector_layer",
        }.get(item.data_type, "catalog.view_dataresource")
        require_features(user, project_id, feature)


def check_snapshot(snapshot, user, project_id: int) -> None:
    """Inspect real references, including hidden layers and nested comparison state."""
    from apps.catalog.models import MapLayer
    from apps.raster.models import RasterDataset

    resources, layers, rasters, outputs = set(), set(), set(), set()

    def walk(value, depth=0):
        if depth > 64:
            raise ComputeError("工程引用结构过深，无法核对分享依赖", 400)
        if isinstance(value, dict):
            source = value.get("sourceResource")
            if isinstance(source, dict) and type(source.get("id")) is int:
                resources.add(source["id"])
            for key, item in value.items():
                destination = {
                    "resourceId": resources,
                    "dataResourceId": resources,
                    "layerId": layers,
                    "mapLayerId": layers,
                    "datasetId": rasters,
                    "rasterDatasetId": rasters,
                    "computeOutputId": outputs,
                }.get(key)
                if destination is not None and type(item) is int:
                    destination.add(item)
                if key in {"resourceIds", "resultResourceIds"} and isinstance(
                    item, list
                ):
                    resources.update(i for i in item if type(i) is int)
                walk(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                walk(item, depth + 1)

    walk(snapshot)
    for model, identities in ((MapLayer, layers), (RasterDataset, rasters)):
        for identity in identities:
            item = model._base_manager.filter(
                pk=identity, project_tag_id=project_id
            ).first()
            with actor_scope(user, project_id):
                if item is None or not user_can_access(item, user):
                    raise ComputeError("工程包含不可访问的图层或影像，无法分享", 403)
            if item.data_resource_id:
                resources.add(item.data_resource_id)
    for identity in resources:
        _resource(user, project_id, identity)
    for identity in outputs:
        output = ComputeOutput.objects.filter(
            pk=identity, task__project_tag_id=project_id
        ).first()
        if output is None or not can_read_shared_output(output, user):
            raise ComputeError("工程包含未授权的临时计算结果，请先分享对应结果", 403)


def _output_dependencies(output, user, project_id: int) -> None:
    if (
        output.expired
        or output.task.status != "succeeded"
        or not app_path(output.path).is_file()
    ):
        raise ComputeError("计算结果尚未完成、已过期或文件不存在", 404)
    records = list(output.task.input_records.all())
    if not records or any(item.resource_id is None for item in records):
        raise ComputeError("计算输入已删除或来源不完整，无法核对结果分享权限", 403)
    for item in records:
        _resource(user, project_id, item.resource_id)
    imported = ComputeImport.objects.filter(
        output=output, resource__isnull=False
    ).first()
    if imported:
        _resource(user, project_id, imported.resource_id)


def source_object(kind: str, object_id: int, project_id: int):
    model = {
        "workspace": WorkspaceScene,
        "composition": MapComposition,
        "compute_output": ComputeOutput,
    }.get(kind)
    if model is None:
        raise ComputeError("分享类型无效")
    query = model._base_manager.filter(pk=object_id)
    query = query.filter(
        **{
            "task__project_tag_id"
            if kind == "compute_output"
            else "project_tag_id": project_id
        }
    )
    item = query.first()
    if item is None:
        raise ComputeError("分享对象不存在或不属于当前项目", 404)
    if kind == "workspace" and item.status != "active":
        raise ComputeError("工程已停用，无法分享", 404)
    return item


def validate_share(kind: str, object_id: int, sender, recipient, project_id: int):
    """Both sides must retain live membership, feature and dependency access."""
    if sender.id == recipient.id:
        raise ComputeError("不能向自己发送分享邀请")
    item = source_object(kind, object_id, project_id)
    for user in (sender, recipient):
        feature = {
            "workspace": "catalog.view_workspacescene",
            "composition": "catalog.view_mapcomposition",
        }.get(kind)
        require_features(
            user, project_id, "core.browse_data", *([feature] if feature else [])
        )
    if kind == "compute_output":
        if item.task.owner_id != sender.id and not permission(sender, "manage_tasks"):
            raise ComputeError("只有结果所属用户或有权计算管理员可以分享", 403)
        for user in (sender, recipient):
            if not (
                permission(user, "view_own_task") or permission(user, "manage_tasks")
            ):
                raise ComputeError("账号没有查看计算结果的功能权限", 403)
            _output_dependencies(item, user, project_id)
    else:
        if item.owner_id != sender.id and not user_has_full_data_access(sender):
            raise ComputeError("只有对象所属用户或有权管理员可以分享", 403)
        versions = (
            list(
                MapCompositionVersion._base_manager.filter(
                    composition=item, project_tag_id=project_id
                )
            )
            if kind == "composition"
            else []
        )
        snapshots = (
            [item.snapshot]
            if kind == "workspace"
            else [
                item.source_workspace_snapshot,
                item.project.snapshot,
                *[version.workspace_snapshot for version in versions],
                {
                    "resourceIds": [
                        entry["id"]
                        for version in versions
                        for entry in version.resource_manifest
                        if isinstance(entry, dict) and type(entry.get("id")) is int
                    ]
                },
            ]
        )
        for user in (sender, recipient):
            for snapshot in snapshots:
                check_snapshot(snapshot, user, project_id)
    return item


def valid_accepted(invitation) -> bool:
    if invitation.status != "accepted":
        return False
    try:
        validate_share(
            invitation.kind,
            invitation.object_id,
            invitation.sender,
            invitation.recipient,
            invitation.project_tag_id,
        )
        return True
    except ComputeError:
        return False


def can_read_shared_output(output, user) -> bool:
    """A single output grant never participates in task_access()."""
    if output.task.owner_id == user.id or permission(user, "manage_tasks"):
        try:
            require_features(user, output.task.project_tag_id, "core.browse_data")
            if not (
                permission(user, "view_own_task") or permission(user, "manage_tasks")
            ):
                return False
            _output_dependencies(output, user, output.task.project_tag_id)
            return True
        except ComputeError:
            return False
    return any(
        valid_accepted(invitation)
        for invitation in ShareInvitation._base_manager.filter(
            kind="compute_output",
            object_id=output.id,
            recipient=user,
            project_tag_id=output.task.project_tag_id,
            status="accepted",
        ).select_related("sender", "recipient")
    )


def shared_composition_ids(user) -> list[int]:
    from apps.projects.context import selected_project_id

    return [
        invitation.object_id
        for invitation in ShareInvitation.objects.filter(
            kind="composition",
            recipient=user,
            status="accepted",
            project_tag_id=selected_project_id(),
        ).select_related("sender", "recipient")
        if valid_accepted(invitation)
    ]


def has_shared_composition(composition, user) -> bool:
    return any(
        valid_accepted(invitation)
        for invitation in ShareInvitation._base_manager.filter(
            kind="composition",
            object_id=composition.id,
            recipient=user,
            project_tag_id=composition.project_tag_id,
            status="accepted",
        ).select_related("sender", "recipient")
    )
