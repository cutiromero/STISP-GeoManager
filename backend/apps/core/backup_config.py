from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit
from django.conf import settings
from django.utils import timezone

from apps.core.config import load_runtime_config_document, write_runtime_config_document

PLAN_TYPES = ("platform", "research")
TARGET_TYPES = ("local", "object_storage")
PROVIDER_TYPES = ("s3_compatible",)
DAILY_AT_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class BackupConfigError(ValueError):
    pass


@dataclass(frozen=True)
class BackupPlanSettings:
    enabled: bool
    daily_at: str
    target: str
    retention_count: int
    include_logs: bool


@dataclass(frozen=True)
class LocalBackupTargetSettings:
    directory: str

    @property
    def configured(self) -> bool:
        return True


@dataclass(frozen=True)
class ObjectStorageBackupSettings:
    provider: str
    endpoint: str
    region: str
    bucket: str
    prefix: str
    access_key_id: str
    secret_access_key: str

    @property
    def configured(self) -> bool:
        return all(
            (
                self.provider,
                self.endpoint,
                self.region,
                self.bucket,
                self.access_key_id,
                self.secret_access_key,
            )
        )

    @property
    def secret_preview(self) -> str:
        if not self.secret_access_key:
            return ""
        suffix = self.secret_access_key[-4:]
        return f"******{suffix}"


@dataclass(frozen=True)
class BackupSettings:
    plans: dict[str, BackupPlanSettings]
    local: LocalBackupTargetSettings
    object_storage: ObjectStorageBackupSettings


def current_backup_settings() -> BackupSettings:
    raw = load_runtime_config_document(settings.PROJECT_CONFIG)
    return backup_settings_from_document(raw)


def backup_settings_from_document(raw: dict[str, Any]) -> BackupSettings:
    backup = _backup_table(raw)
    local = _local_settings(backup.get("local"))
    object_storage = _object_storage_settings(backup.get("object_storage"))
    plans_table = backup.get("plans") if _is_table(backup.get("plans")) else {}
    return BackupSettings(
        plans={
            "platform": _plan_settings(
                plans_table.get("platform") if _is_table(plans_table) else None,
                default_daily_at="03:00",
                default_target="object_storage",
                default_retention_count=7,
                default_include_logs=False,
            ),
            "research": _plan_settings(
                plans_table.get("research") if _is_table(plans_table) else None,
                default_daily_at="02:00",
                default_target="object_storage",
                default_retention_count=7,
                default_include_logs=False,
            ),
        },
        local=local,
        object_storage=object_storage,
    )


def serialize_backup_settings(value: BackupSettings | None = None) -> dict[str, Any]:
    backup = value or current_backup_settings()
    return {
        "plans": {key: _serialize_plan(plan) for key, plan in backup.plans.items()},
        "local": {
            "directory": backup.local.directory,
            "configured": backup.local.configured,
        },
        "objectStorage": {
            "provider": backup.object_storage.provider,
            "endpoint": backup.object_storage.endpoint,
            "region": backup.object_storage.region,
            "bucket": backup.object_storage.bucket,
            "prefix": backup.object_storage.prefix,
            "accessKeyId": backup.object_storage.access_key_id,
            "secretConfigured": bool(backup.object_storage.secret_access_key),
            "secretPreview": backup.object_storage.secret_preview,
            "configured": backup.object_storage.configured,
        },
        "updatedAt": timezone.localtime().isoformat(),
    }


def update_backup_settings(payload: dict[str, Any]) -> BackupSettings:
    raw = load_runtime_config_document(settings.PROJECT_CONFIG)
    backup = _ensure_backup_table(raw)

    if "plans" in payload:
        plans_payload = payload["plans"]
        if not isinstance(plans_payload, dict):
            raise BackupConfigError("plans 必须是对象")
        plans = _ensure_table(backup, "plans")
        for plan_type in PLAN_TYPES:
            if plan_type in plans_payload:
                plan = _validated_plan_payload(plans_payload[plan_type], plan_type)
                plan_table = _ensure_table(plans, plan_type)
                plan_table["enabled"] = plan.enabled
                plan_table["daily_at"] = plan.daily_at
                plan_table["target"] = plan.target
                plan_table["retention_count"] = plan.retention_count
                plan_table["include_logs"] = (
                    plan.include_logs if plan_type == "platform" else False
                )

    if "local" in payload:
        local_payload = payload["local"]
        if not isinstance(local_payload, dict):
            raise BackupConfigError("local 必须是对象")
        local = _ensure_table(backup, "local")
        if "directory" in local_payload:
            directory = _optional_string(local_payload["directory"], "local.directory")
            if directory and not Path(directory).expanduser().is_absolute():
                raise BackupConfigError("本地备份目录必须是绝对路径或留空")
            local["directory"] = directory

    if "objectStorage" in payload:
        object_payload = payload["objectStorage"]
        if not isinstance(object_payload, dict):
            raise BackupConfigError("objectStorage 必须是对象")
        object_storage = _ensure_table(backup, "object_storage")
        _update_object_storage_table(object_storage, object_payload)

    write_runtime_config_document(settings.PROJECT_CONFIG, raw)
    return backup_settings_from_document(raw)


def object_storage_from_payload(
    payload: dict[str, Any] | None,
) -> ObjectStorageBackupSettings:
    if not payload:
        return current_backup_settings().object_storage
    saved = current_backup_settings().object_storage
    provider = _optional_string(
        payload.get("provider", saved.provider), "objectStorage.provider"
    )
    if provider not in PROVIDER_TYPES:
        raise BackupConfigError("objectStorage.provider 仅支持 s3_compatible")
    secret = _optional_string(
        payload.get("secretAccessKey", saved.secret_access_key),
        "objectStorage.secretAccessKey",
    )
    if payload.get("clearSecret"):
        secret = ""
    return ObjectStorageBackupSettings(
        provider=provider,
        endpoint=_optional_string(
            payload.get("endpoint", saved.endpoint), "objectStorage.endpoint"
        ),
        region=_optional_string(
            payload.get("region", saved.region), "objectStorage.region"
        ),
        bucket=_optional_string(
            payload.get("bucket", saved.bucket), "objectStorage.bucket"
        ),
        prefix=_optional_string(
            payload.get("prefix", saved.prefix), "objectStorage.prefix"
        ),
        access_key_id=_optional_string(
            payload.get("accessKeyId", saved.access_key_id),
            "objectStorage.accessKeyId",
        ),
        secret_access_key=secret,
    )


def local_target_from_payload(
    payload: dict[str, Any] | None,
) -> LocalBackupTargetSettings:
    saved = current_backup_settings().local
    if not payload:
        return saved
    directory = _optional_string(
        payload.get("directory", saved.directory), "local.directory"
    )
    if directory and not Path(directory).expanduser().is_absolute():
        raise BackupConfigError("本地备份目录必须是绝对路径或留空")
    return LocalBackupTargetSettings(directory=directory)


def plan_for(plan_type: str) -> BackupPlanSettings:
    if plan_type not in PLAN_TYPES:
        raise BackupConfigError("planType 仅支持 platform 或 research")
    return current_backup_settings().plans[plan_type]


def _serialize_plan(plan: BackupPlanSettings) -> dict[str, Any]:
    return {
        "enabled": plan.enabled,
        "dailyAt": plan.daily_at,
        "target": plan.target,
        "retentionCount": plan.retention_count,
        "includeLogs": plan.include_logs,
    }


def _backup_table(raw: dict[str, Any]) -> dict[str, Any]:
    application = raw.get("application")
    if not _is_table(application):
        return {}
    backup = application.get("backup")
    return backup if _is_table(backup) else {}


def _ensure_backup_table(raw: dict[str, Any]) -> dict[str, Any]:
    application = raw.get("application")
    if not _is_table(application):
        raise BackupConfigError("缺少 application 配置段")
    if not _is_table(application.get("backup")):
        application["backup"] = tomlkit.table()
    return application["backup"]


def _ensure_table(parent: dict[str, Any], key: str) -> dict[str, Any]:
    if not _is_table(parent.get(key)):
        parent[key] = tomlkit.table()
    return parent[key]


def _plan_settings(
    raw: Any,
    *,
    default_daily_at: str,
    default_target: str,
    default_retention_count: int,
    default_include_logs: bool,
) -> BackupPlanSettings:
    table = raw if _is_table(raw) else {}
    return BackupPlanSettings(
        enabled=_bool(table.get("enabled", False), "enabled"),
        daily_at=_daily_at(table.get("daily_at", default_daily_at), "dailyAt"),
        target=_target_type(table.get("target", default_target), "target"),
        retention_count=_retention_count(
            table.get("retention_count", default_retention_count), "retentionCount"
        ),
        include_logs=_bool(
            table.get("include_logs", default_include_logs), "includeLogs"
        ),
    )


def _validated_plan_payload(value: Any, plan_type: str) -> BackupPlanSettings:
    if not isinstance(value, dict):
        raise BackupConfigError(f"plans.{plan_type} 必须是对象")
    required = ("enabled", "dailyAt", "target", "retentionCount", "includeLogs")
    missing = [key for key in required if key not in value]
    if missing:
        raise BackupConfigError(f"plans.{plan_type} 缺少字段：{', '.join(missing)}")
    return BackupPlanSettings(
        enabled=_bool(value["enabled"], "enabled"),
        daily_at=_daily_at(value["dailyAt"], "dailyAt"),
        target=_target_type(value["target"], "target"),
        retention_count=_retention_count(value["retentionCount"], "retentionCount"),
        include_logs=_bool(value["includeLogs"], "includeLogs"),
    )


def _local_settings(raw: Any) -> LocalBackupTargetSettings:
    table = raw if _is_table(raw) else {}
    return LocalBackupTargetSettings(
        directory=_optional_string(table.get("directory", ""), "local.directory")
    )


def _object_storage_settings(raw: Any) -> ObjectStorageBackupSettings:
    table = raw if _is_table(raw) else {}
    provider = _optional_string(
        table.get("provider", "s3_compatible"), "objectStorage.provider"
    )
    if provider and provider not in PROVIDER_TYPES:
        provider = "s3_compatible"
    return ObjectStorageBackupSettings(
        provider=provider or "s3_compatible",
        endpoint=_optional_string(table.get("endpoint", ""), "objectStorage.endpoint"),
        region=_optional_string(table.get("region", ""), "objectStorage.region"),
        bucket=_optional_string(table.get("bucket", ""), "objectStorage.bucket"),
        prefix=_optional_string(table.get("prefix", ""), "objectStorage.prefix"),
        access_key_id=_optional_string(
            table.get("access_key_id", ""), "objectStorage.accessKeyId"
        ),
        secret_access_key=_optional_string(
            table.get("secret_access_key", ""), "objectStorage.secretAccessKey"
        ),
    )


def _update_object_storage_table(
    target: dict[str, Any], payload: dict[str, Any]
) -> None:
    if "provider" in payload:
        provider = _optional_string(payload["provider"], "objectStorage.provider")
        if provider not in PROVIDER_TYPES:
            raise BackupConfigError("objectStorage.provider 仅支持 s3_compatible")
        target["provider"] = provider
    for api_key, toml_key in (
        ("endpoint", "endpoint"),
        ("region", "region"),
        ("bucket", "bucket"),
        ("prefix", "prefix"),
        ("accessKeyId", "access_key_id"),
    ):
        if api_key in payload:
            target[toml_key] = _optional_string(
                payload[api_key], f"objectStorage.{api_key}"
            )
    if payload.get("clearSecret"):
        target["secret_access_key"] = ""
    elif "secretAccessKey" in payload:
        target["secret_access_key"] = _optional_string(
            payload["secretAccessKey"], "objectStorage.secretAccessKey"
        )


def _optional_string(value: Any, key: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise BackupConfigError(f"{key} 必须是字符串")
    return value.strip()


def _bool(value: Any, key: str) -> bool:
    if not isinstance(value, bool):
        raise BackupConfigError(f"{key} 必须是布尔值")
    return value


def _daily_at(value: Any, key: str) -> str:
    text = _optional_string(value, key)
    if not DAILY_AT_PATTERN.match(text):
        raise BackupConfigError(f"{key} 必须是 HH:mm 格式")
    return text


def _target_type(value: Any, key: str) -> str:
    text = _optional_string(value, key)
    if text not in TARGET_TYPES:
        raise BackupConfigError(f"{key} 仅支持 local 或 object_storage")
    return text


def _retention_count(value: Any, key: str) -> int:
    if not isinstance(value, int) or value < 1 or value > 365:
        raise BackupConfigError(f"{key} 必须是 1 到 365 之间的整数")
    return value


def _is_table(value: Any) -> bool:
    return (
        hasattr(value, "get")
        and hasattr(value, "items")
        and hasattr(value, "__setitem__")
        and not isinstance(value, (str, bytes, list, tuple))
    )
