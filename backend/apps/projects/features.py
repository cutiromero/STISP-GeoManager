import math

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.audit.service import log_operation
from .context import is_superadmin
from .models import ProjectFeature, ProjectFeatureSetting

MONITOR_FEATURE = "ecology_monitor"
UNSET = object()


def validate_config(key, config):
    if config is None:
        return
    if not isinstance(config, dict):
        raise ValidationError("项目功能配置必须是 JSON 对象或 null")
    if key != MONITOR_FEATURE:
        return
    title = config.get("title")
    view = config.get("initialView")
    if not isinstance(title, str) or not title.strip():
        raise ValidationError("大屏配置必须包含非空 title")
    if config.get("source") not in ("tarim_poplar_mock", "remote_sensing_products"):
        raise ValidationError("未知监测数据源")
    if "scenes" in config:
        scenes = config["scenes"]
        if (
            not isinstance(scenes, list)
            or not 1 <= len(scenes) <= 3
            or any(
                not isinstance(value, str)
                or value not in {"spartina", "wildfire", "landcover"}
                for value in scenes
            )
            or len(set(scenes)) != len(scenes)
        ):
            raise ValidationError("监测场景须为已支持场景的不重复列表")
    if not isinstance(view, dict):
        raise ValidationError("大屏配置必须包含 initialView")
    center = view.get("center")
    if not isinstance(center, list) or len(center) != 2:
        raise ValidationError("initialView.center 必须是经纬度数组")
    for value, lower, upper in [
        (center[0], -180, 180),
        (center[1], -90, 90),
        (view.get("zoom"), 0, 22),
        (view.get("regionZoom"), 0, 22),
    ]:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not lower <= value <= upper
        ):
            raise ValidationError("大屏初始视角的坐标或缩放级别无效")


def serialize_feature(feature):
    return {"key": feature.key, "globallyEnabled": feature.globally_enabled}


def feature_state(project, features):
    settings = {row.feature_id: row for row in project.feature_settings.all()}
    enabled = [
        feature.key
        for feature in features
        if project.is_active
        and (
            feature.globally_enabled
            or (feature.id in settings and settings[feature.id].enabled)
        )
    ]
    monitor = next(
        (
            settings.get(feature.id)
            for feature in features
            if feature.key == MONITOR_FEATURE
        ),
        None,
    )
    return {
        "enabledFeatures": enabled,
        "configuredFeatures": [
            feature.key
            for feature in features
            if feature.id in settings and settings[feature.id].enabled
        ],
        "monitorConfig": monitor.config
        if MONITOR_FEATURE in enabled and monitor is not None
        else None,
    }


@transaction.atomic
def set_feature(
    user, feature, *, project=None, enabled=UNSET, config=UNSET, request=None
):
    if not is_superadmin(user):
        raise PermissionDenied("只有超级管理员可以维护项目功能")
    if enabled is not UNSET and type(enabled) is not bool:
        raise ValidationError("enabled 必须是布尔值")
    if config is not UNSET:
        validate_config(feature.key, config)
    if project is None:
        if config is not UNSET or enabled is UNSET:
            raise ValidationError("全局设置只接受 enabled 布尔值")
        row = ProjectFeature.objects.select_for_update().get(pk=feature.pk)
        before = row.globally_enabled
        row.globally_enabled = enabled
        row.save(update_fields=["globally_enabled"])
        detail = f"全局 {before} -> {enabled}"
    else:
        if enabled is UNSET and config is UNSET:
            raise ValidationError("至少提供 enabled 或 config")
        ProjectFeature.objects.select_for_update().get(pk=feature.pk)
        row, _ = ProjectFeatureSetting.objects.get_or_create(
            project=project, feature=feature
        )
        before = {"enabled": row.enabled, "config": row.config}
        if enabled is not UNSET:
            row.enabled = enabled
        if config is not UNSET:
            row.config = config
        row.save()
        detail = f"项目 {project.code} {before} -> enabled={row.enabled}, config={row.config}"
    log_operation(
        user,
        "项目功能",
        "设置功能",
        "success",
        f"{feature.key}: {detail}",
        request,
        target_type="project_feature",
        target_id=project.pk if project is not None else feature.pk,
        target_code=feature.key,
        target_name=project.name if project is not None else "所有项目",
    )
    return row
