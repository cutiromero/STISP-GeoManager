"""Shared revision-checked workspace writes for HTTP and Agent adapters."""

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.compute.packages import ComputeError
from .models import WorkspaceScene
from .share_access import check_snapshot


def save_revision(scene, expected, values, *, user, precondition=None):
    try:
        stamp = parse_datetime(expected) if isinstance(expected, str) else None
    except ValueError:
        stamp = None
    if stamp is None or timezone.is_naive(stamp):
        raise ComputeError("保存须提供最后读取的 expectedUpdatedAt")
    with transaction.atomic():
        query = WorkspaceScene.objects.filter(
            pk=scene.pk, owner_id=scene.owner_id, updated_at=stamp
        )
        if not query.update(updated_at=F("updated_at")):
            raise ComputeError(
                "工程已被其他会话更新。当前修改未保存，请保留修改并重新读取工程。", 409
            )
        from django.contrib.auth import get_user_model
        from apps.core.permissions import has_feature_perm
        from .permissions import user_can_bypass_owner_only
        from apps.projects.access import can_access_project

        actor = get_user_model().objects.filter(pk=user.pk, is_active=True).first()
        if (
            actor is None
            or not can_access_project(actor, scene.project_tag_id)
            or (actor.pk != scene.owner_id and not user_can_bypass_owner_only(actor))
        ):
            raise ComputeError("当前账号无权修改该工程", 403)
        if values and not has_feature_perm(actor, "catalog.change_workspacescene"):
            raise ComputeError("当前账号没有修改工程的权限", 403)
        if precondition is not None:
            precondition()
        for key, value in values.items():
            setattr(scene, key, value)
        scene.prepare_project_scope()
        scene.validate_project_relations()
        if "snapshot" in values:
            check_snapshot(values["snapshot"], actor, scene.project_tag_id)
        query.update(**values, updated_at=timezone.now())
