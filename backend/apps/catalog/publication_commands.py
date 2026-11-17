"""Shared publication admission and short metadata writes for pages and tools."""

import json

from django.db import transaction
from django.db.models import F
from django.http import JsonResponse
from django.utils import timezone

from apps.compute.packages import ComputeError
from apps.core.permissions import has_feature_perm
from apps.core.storage import app_path
from .models import MapComposition, ResultArtifact
from .share_access import check_snapshot


def checked(value):
    if isinstance(value, JsonResponse):
        raise ComputeError(json.loads(value.content)["detail"], value.status_code)
    return value


def publication_target(user, kind, identity, group_ids, version_number=None):
    """Return authorized real objects; no published metadata is changed here."""
    if kind == "composition":
        from .map_compositions import (
            _manageable_composition,
            _group_ids,
            _validate_selectable_groups,
        )

        if not has_feature_perm(user, "catalog.publish_mapcomposition"):
            raise ComputeError("没有专题图发布权限", 403)
        item = _manageable_composition(user, identity)
        if item is None:
            raise ComputeError("出图稿不存在", 404)
        if type(version_number) is not int or version_number <= 0:
            raise ComputeError("versionNumber 必须是正整数")
        version = item.versions.filter(version_number=version_number).first()
        if version is None:
            raise ComputeError("专题成果版本不存在", 404)
        files = [version.preview_path, version.artifact_path]
        groups = checked(_group_ids(group_ids, required=False))
        error = _validate_selectable_groups(groups, user)
        check_snapshot(version.workspace_snapshot, user, item.project_tag_id)
        check_snapshot(
            {
                "resourceIds": [
                    v["id"]
                    for v in version.resource_manifest
                    if isinstance(v, dict) and type(v.get("id")) is int
                ]
            },
            user,
            item.project_tag_id,
        )
    elif kind == "result":
        from .results import (
            _result_for_user,
            _user_can_manage_result,
            _positive_integer_list,
            _validate_access_groups,
            _related_resources,
        )

        if not has_feature_perm(user, "catalog.publish_resultartifact"):
            raise ComputeError("没有成果发布权限", 403)
        item = _result_for_user(user, identity)
        if item is None or not _user_can_manage_result(item, user):
            raise ComputeError("成果不存在", 404)
        version = None
        files = [item.file_path]
        groups = checked(_positive_integer_list(group_ids))
        error = _validate_access_groups(groups, user)
        checked(
            _related_resources(
                list(item.related_resources.values_list("pk", flat=True)),
                user,
                item.project_tag_id,
            )
        )
    else:
        raise ComputeError("发布类型仅支持result或composition")
    if error:
        raise ComputeError(error)
    if not all(path and app_path(path).is_file() for path in files):
        raise ComputeError(
            "专题成果文件不可用，请从原工程重新生成后发布"
            if kind == "composition"
            else "成果文件不可用，请重新生成后发布"
        )
    return item, version, groups, files


def publish(
    user,
    kind,
    identity,
    group_ids,
    *,
    version_number=None,
    expected_updated_at=None,
    resource_ids=None,
):
    model = MapComposition if kind == "composition" else ResultArtifact
    with transaction.atomic():
        query = model.objects.filter(pk=identity)
        if expected_updated_at is not None:
            query = query.filter(updated_at=expected_updated_at)
        # Reserve SQLite's writer before rereading ACLs and the exact revision.
        if not query.update(updated_at=F("updated_at")):
            raise ComputeError("成果已更新，请重新读取后预览发布范围", 409)
        item, version, groups, _ = publication_target(
            user,
            kind,
            identity,
            group_ids,
            version_number,
        )
        related = None
        if resource_ids is not None:
            if kind != "result":
                raise ComputeError("专题图发布不接受关联资料变更")
            from .results import _related_resources

            related = checked(
                _related_resources(resource_ids, user, item.project_tag_id)
            )
        item.status, item.published_by, item.published_at = (
            "published",
            user,
            timezone.now(),
        )
        fields = ["status", "published_by", "published_at", "updated_at"]
        if kind == "composition":
            item.published_version = version
            fields.append("published_version")
        item.save(update_fields=fields)
        (item.audience_groups if kind == "composition" else item.access_groups).set(
            groups
        )
        if related is not None:
            item.related_resources.set(related)
        return item
