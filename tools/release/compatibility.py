"""在候选副本上以基线代码检查并执行回滚事务内的旧列 INSERT。"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import runpy
import sys
import uuid


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def probe(context):
    code = Path(context["baselineRoot"]).resolve()
    config = Path(context["config"]).resolve()
    sys.path.insert(0, str(code / "backend"))
    from apps.core import config as configuration

    configuration.resolve_config_path = lambda program_root: config
    sys.argv = [str(code / "backend/manage.py"), "check"]
    runpy.run_path(sys.argv[0], run_name="__main__")
    from django.apps import apps
    from django.conf import settings
    from django.db import connection

    require(settings.PROGRAM_ROOT.resolve() == code, "未加载基线代码")
    require(settings.PROJECT_CONFIG.config_path.resolve() == config, "未加载候选配置")
    require(
        Path(connection.settings_dict["NAME"]).resolve()
        == Path(context["database"]).resolve(),
        "未连接指定候选数据库",
    )
    require(
        Path(context["database"]).resolve().is_relative_to(config.parent),
        "兼容检查不得访问候选根以外数据库",
    )
    models = [apps.get_model(app, model) for app, model in context["models"]]
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT app, name FROM django_migrations ORDER BY app, name"
        ).fetchall()
    result = smoke(models, connection)
    return {
        **result,
        "djangoCheck": True,
        "archiveSha256": context["archiveSha256"],
        "baseCommit": context["baseCommit"],
        "classificationDigest": context["classificationDigest"],
    }


def smoke(models, connection):
    from django.db import transaction

    counts = {model._meta.label: model._base_manager.count() for model in models}
    for model in models:
        list(model._base_manager.values()[:1])
    inserted = []
    visiting = set()

    def insert(model):
        label = model._meta.label
        require(label not in visiting, "循环外键无法自动建立旧代码插入样本")
        visiting.add(label)
        fields, values = [], []
        token = uuid.uuid4().hex
        for field in model._meta.local_concrete_fields:
            kind = field.get_internal_type()
            if kind in {"AutoField", "BigAutoField", "SmallAutoField"}:
                continue
            if field.is_relation:
                related = field.remote_field.model
                existing = related._base_manager.values_list(
                    field.target_field.attname, flat=True
                ).first()
                if existing is None and not field.null:
                    insert(related)
                    existing = related._base_manager.values_list(
                        field.target_field.attname, flat=True
                    ).first()
                value = existing
            elif field.has_default():
                value = field.get_default()
            elif field.null:
                value = None
            elif kind in {
                "CharField",
                "TextField",
                "SlugField",
                "EmailField",
                "URLField",
                "FileField",
                "ImageField",
            }:
                value = token[: field.max_length] if field.max_length else token
            elif kind == "UUIDField":
                value = uuid.uuid4()
            elif kind == "JSONField":
                value = {}
            elif kind == "BooleanField":
                value = False
            elif kind in {"DateTimeField", "DateField", "TimeField"}:
                now = datetime.now(timezone.utc)
                value = (
                    now
                    if kind == "DateTimeField"
                    else date.today()
                    if kind == "DateField"
                    else time(12)
                )
            elif kind == "DurationField":
                value = timedelta()
            elif kind == "DecimalField":
                value = Decimal(0)
            elif kind == "BinaryField":
                value = b""
            elif "Integer" in kind or kind == "FloatField":
                value = 1
            else:
                raise AssertionError("无法构造基线字段：" + label + "." + field.name)
            fields.append(connection.ops.quote_name(field.column))
            values.append(field.get_db_prep_save(value, connection))
        with connection.cursor() as cursor:
            statement = "INSERT INTO " + connection.ops.quote_name(model._meta.db_table)
            statement += (
                " ("
                + ",".join(fields)
                + ") VALUES ("
                + ",".join(["%s"] * len(values))
                + ")"
                if fields
                else " DEFAULT VALUES"
            )
            cursor.execute(statement, values)
            require(cursor.rowcount == 1, "旧列集 INSERT 没有写入一行")
        inserted.append(label)
        visiting.remove(label)

    with transaction.atomic():
        for model in models:
            insert(model)
        with connection.cursor() as cursor:
            require(
                not cursor.execute("PRAGMA foreign_key_check").fetchall(),
                "候选库外键检查失败",
            )
        transaction.set_rollback(True)
    require(
        counts == {model._meta.label: model._base_manager.count() for model in models},
        "旧代码兼容事务回滚后行数不符",
    )
    return {
        "passed": True,
        "read": True,
        "insertRolledBack": True,
        "models": sorted(set(inserted)),
    }


def run(config, release, root):
    import subprocess

    if __package__:
        from . import server
    else:
        import server

    server.require(
        Path(config["productionConfig"]).resolve().parent == Path(root).resolve()
        and server.database(config).resolve().is_relative_to(Path(root).resolve()),
        "旧代码兼容检查仅允许使用候选根内的配置和数据库",
    )
    classification = release["migrationClassification"]
    context = {
        "baselineRoot": release["baseline"]["appRoot"],
        "config": config["productionConfig"],
        "database": str(server.database(config)),
        "models": sorted(
            {(item["app"], item["model"]) for item in classification["affectedModels"]}
        ),
        "archiveSha256": release["package"]["sha256"],
        "baseCommit": release["baseline"]["commit"],
        "classificationDigest": server.digest(classification),
    }
    script = (
        "import compatibility,json;print(json.dumps(compatibility.probe("
        + repr(context)
        + "),ensure_ascii=False))"
    )
    log = Path(root) / "baseline-compatibility.private.log"
    with log.open("xb") as output:
        done = subprocess.run(
            [config["python"], "-c", script],
            cwd=Path(__file__).parent,
            env=server.environment(config, release["baseline"]["appRoot"]),
            stdout=output,
            stderr=subprocess.STDOUT,
            timeout=config["managementSeconds"],
        )
    server.require(
        done.returncode == 0, "旧代码兼容检查失败，候选不接受；检查候选私有日志"
    )
    result = json.loads(log.read_text().splitlines()[-1])
    server.require(
        result.get("passed") is True and result.get("insertRolledBack") is True,
        "旧代码兼容证据不完整",
    )
    return result
