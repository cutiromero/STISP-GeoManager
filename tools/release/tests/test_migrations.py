"""迁移 AST 分类不执行源码，对不明或破坏性操作默认拒绝。"""

import hashlib
from pathlib import Path

import pytest

from tools.release import migrations

ROOT = Path(__file__).resolve().parents[3]
NEW_TABLE = "migrations.CreateModel(name='Fresh', fields=[('id', models.AutoField(primary_key=True))])"


def source(operation, extra=""):
    return (
        "from django.db import migrations, models\n"
        + extra
        + "\nclass Migration(migrations.Migration):\n    dependencies = []\n    operations = ["
        + operation
        + "]\n"
    )


@pytest.mark.parametrize(
    "operation",
    [
        "",
        NEW_TABLE,
        "migrations.AddField(model_name='old', name='extra', field=models.TextField(null=True))",
        "migrations.AddField(model_name='old', name='extra', field=models.JSONField(default=dict, db_default={}))",
        "migrations.AddField(model_name='old', name='extra', field=models.IntegerField(db_default=models.Value(0)))",
        NEW_TABLE
        + ", migrations.AddField(model_name='fresh', name='extra', field=models.TextField())",
        NEW_TABLE
        + ", migrations.AddIndex(model_name='fresh', index=models.Index(fields=['id'], name='fresh_idx'))",
        NEW_TABLE
        + ", migrations.AddConstraint(model_name='fresh', constraint=models.UniqueConstraint(fields=['id'], name='fresh_unique'))",
        NEW_TABLE
        + ", migrations.AddConstraint(model_name='fresh', constraint=models.CheckConstraint(condition=models.Q(id__gte=0), name='positive'))",
        NEW_TABLE
        + ", migrations.RunSQL(\"INSERT INTO app_fresh (id) VALUES (1)\", '')",
        "migrations.RunSQL('')",
        "migrations.RunPython(migrations.RunPython.noop)",
    ],
)
def test_allowed_operations(operation):
    report, _ = migrations.classify_file(
        "backend/apps/app/migrations/0002_safe.py", source(operation)
    )
    assert report["allowed"], report


@pytest.mark.parametrize(
    "operation",
    [
        "migrations.DeleteModel(name='Old')",
        "migrations.RenameModel(old_name='Old', new_name='Fresh')",
        "migrations.RemoveField(model_name='old', name='value')",
        "migrations.RenameField(model_name='old', old_name='value', new_name='new')",
        "migrations.AlterField(model_name='old', name='value', field=models.TextField(null=True))",
        "migrations.AlterModelTable(name='old', table='fresh')",
        "migrations.AlterUniqueTogether(name='old', unique_together={('id', 'value')})",
        "migrations.AddField(model_name='old', name='extra', field=models.JSONField(default=dict))",
        "migrations.AddField(model_name='old', name='extra', field=models.TextField(db_default=None))",
        "migrations.AddField(model_name='old', name='extra', field=models.TextField(db_default=models.F('value')))",
        "migrations.AddField(model_name='old', name='extra', field=models.IntegerField(null=True, unique=True))",
        "migrations.AddField(model_name='old', name='extra', field=models.IntegerField(db_default=1, primary_key=True))",
        "migrations.AddConstraint(model_name='old', constraint=models.UniqueConstraint(fields=['id'], name='bad'))",
        "migrations.AddIndex(model_name='old', index=models.Index(fields=['id'], name='bad'))",
        "migrations.RemoveIndex(model_name='old', name='idx')",
        "migrations.SeparateDatabaseAndState(database_operations=[], state_operations=[])",
        'migrations.RunSQL("UPDATE app_old SET value = 1")',
        NEW_TABLE
        + ', migrations.RunSQL("INSERT INTO app_fresh (id) SELECT id FROM app_old")',
        NEW_TABLE
        + ', migrations.RunSQL("INSERT INTO app_fresh (id) VALUES (1); DROP TABLE app_old")',
        NEW_TABLE
        + ', migrations.RunSQL("INSERT INTO app_fresh (id) VALUES (danger())")',
        "unknown()",
        "migrations.CreateModel(name='Fresh', fields=[], options={'managed': False})",
        "migrations.CreateModel(name='Fresh', fields=[], bases=(custom.Model,))",
    ],
)
def test_rejected_operations(operation):
    report, _ = migrations.classify_file(
        "backend/apps/app/migrations/0002_bad.py", source(operation)
    )
    assert not report["allowed"]
    assert report["file"].endswith("0002_bad.py")
    assert any(
        item["reason"] and item["operation"] and item["line"]
        for item in report["operations"]
        if not item["allowed"]
    )


@pytest.mark.parametrize(
    "statement,allowed",
    [
        ("fresh.objects.create(id=1)", True),
        ("fresh.objects.using('default').create(id=1)", True),
        ("fresh.objects.using('unverified').create(id=1)", False),
        ("schema_editor = fresh.objects.create(id=1)", False),
        ("fresh.objects.filter(id=1).update(id=2)", True),
        ("fresh.objects.filter(id=1).delete()", False),
        ("old.objects.filter(id=1).first()", True),
        ("old.objects.create(id=1)", False),
        ("old.objects.filter(id=1).update(id=2)", False),
        ("old.objects.all().delete()", False),
        ("schema_editor.execute('DROP TABLE app_old')", False),
        ("__import__('os').system('echo unsafe')", False),
        ("fresh.objects.raw('DELETE FROM app_old')", False),
        ("fresh.objects.create(id=read_secret())", False),
    ],
)
def test_runpython_provenance(statement, allowed):
    extra = (
        "\ndef seed(apps, schema_editor):\n    fresh = apps.get_model('app', 'Fresh')\n    old = apps.get_model('app', 'Old')\n    "
        + statement
        + "\n"
    )
    report, _ = migrations.classify_file(
        "backend/apps/app/migrations/0002_data.py",
        source(
            NEW_TABLE + ", migrations.RunPython(seed, migrations.RunPython.noop)", extra
        ),
    )
    assert report["allowed"] is allowed, report


def test_real_migrations_are_allowed():
    for app, name in (
        ("projects", "0003_project_features"),
        ("compute", "0007_operator_protocol"),
    ):
        path = f"backend/apps/{app}/migrations/{name}.py"
        report, affected = migrations.classify_file(path, (ROOT / path).read_bytes())
        assert report["allowed"], report
        assert len(affected) == (3 if app == "compute" else 0)


@pytest.mark.parametrize("current", [{}, {"old": "b" * 64}])
def test_baseline_changes_rejected(current):
    report = migrations.classify({"old": "a" * 64}, current, lambda name: b"")
    assert not report["allowed"]
    assert "基线迁移被修改或删除" in migrations.rejection(report)


def test_parser_never_executes_source(tmp_path):
    marker = tmp_path / "never"
    text = f"open({str(marker)!r}, 'w').write('bad')\n" + source("")
    report, _ = migrations.classify_file(
        "backend/apps/app/migrations/0002_bad.py", text
    )
    assert not report["allowed"] and not marker.exists()


def test_added_source_digest_is_checked():
    with pytest.raises(ValueError, match="冻结摘要"):
        migrations.classify(
            {},
            {"bad": hashlib.sha256(b"original").hexdigest()},
            lambda name: b"changed",
        )


def test_unused_function_default_cannot_execute_code(tmp_path):
    marker = tmp_path / "never"
    extra = f"\ndef unused(apps, schema_editor=open({str(marker)!r}, 'w')):\n    pass\n"
    report, _ = migrations.classify_file(
        "backend/apps/app/migrations/0002_bad.py", source("", extra)
    )
    assert not report["allowed"] and not marker.exists()


def test_create_model_cannot_alias_a_baseline_table():
    old = "backend/apps/app/migrations/0001_old.py"
    new = "backend/apps/app/migrations/0002_new.py"
    sources = {
        old: source(NEW_TABLE).encode(),
        new: source(
            "migrations.CreateModel(name='Other', fields=[], options={'db_table': 'app_fresh'})"
        ).encode(),
    }
    hashes = {
        name: hashlib.sha256(value).hexdigest() for name, value in sources.items()
    }
    result = migrations.classify({old: hashes[old]}, hashes, sources.__getitem__)
    assert not result["allowed"] and "冲突" in migrations.rejection(result)


def test_migration_outside_known_app_layout_is_rejected():
    report, _ = migrations.classify_file(
        "backend/unknown/migrations/0002.py", source(NEW_TABLE)
    )
    assert not report["allowed"]
