"""在独立 SQLite 上证明 compute.0007 的旧列集插入与模型状态一致。"""

import os
from pathlib import Path
import subprocess

import tomlkit

ROOT = Path(__file__).resolve().parents[3]
PYTHON = "/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin/python"
SCRIPT = r"""
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(sys.argv[1]) / "backend"))
from apps.core import config
config.resolve_config_path = lambda root: Path(sys.argv[2])
os.environ["DJANGO_SETTINGS_MODULE"] = "geomanager.settings"
import django
django.setup()
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
before = [("compute", "0006_nullable_historical_input"), ("projects", "0002_public_project_name")]
executor = MigrationExecutor(connection)
executor.migrate(before)
old_apps = executor.loader.project_state(before).apps
OldTask = old_apps.get_model("compute", "ComputeTask")
assert not {"failure", "field_mappings", "input_collections"} & {field.name for field in OldTask._meta.fields}
user = old_apps.get_model("auth", "User").objects.create(username="legacy")
project = old_apps.get_model("projects", "Project").objects.first()
algorithm = old_apps.get_model("compute", "AlgorithmResource").objects.create(project_tag=project, identifier="legacy", name="legacy", created_by=user)
version = old_apps.get_model("compute", "AlgorithmVersion").objects.create(algorithm=algorithm, version="1", manifest={}, checksum="test", package_path="test")
executor = MigrationExecutor(connection)
executor.migrate([("compute", "0007_operator_protocol"), ("projects", "0003_project_features")])
queries = []
def capture(execute, sql, params, many, context):
    queries.append(sql)
    return execute(sql, params, many, context)
with connection.execute_wrapper(capture):
    task = OldTask.objects.create(project_tag=project, owner=user, version=version, name="legacy", idempotency_key="legacy", request_hash="legacy")
insert = next(sql for sql in queries if sql.startswith("INSERT INTO"))
assert all('"' + column + '"' not in insert for column in ("failure", "field_mappings", "input_collections"))
with connection.cursor() as cursor:
    cursor.execute("SELECT failure, field_mappings, input_collections FROM compute_computetask WHERE id=%s", [task.pk.hex])
    assert [json.loads(value) for value in cursor.fetchone()] == [{}, {}, {}]
    columns = {row[1]: row for row in cursor.execute("PRAGMA table_info(compute_computetask)")}
    assert all(columns[column][3] == 1 and columns[column][4] is not None for column in ("failure", "field_mappings", "input_collections"))
call_command("makemigrations", check=True, dry_run=True, verbosity=1)
from tools.release.compatibility import smoke
before_count = OldTask.objects.count()
result = smoke([OldTask], connection)
assert result["passed"] and result["insertRolledBack"] and result["read"]
assert OldTask.objects.count() == before_count
from tools.release.compatibility import probe
root, candidate_config = Path(sys.argv[1]), Path(sys.argv[2])
pointer = root / ".runtime/config-path"
pointer_before = pointer.read_bytes() if pointer.exists() else None
evidence = probe({"baselineRoot": str(root), "config": str(candidate_config), "database": str(connection.settings_dict["NAME"]), "models": [("compute", "ComputeTask")], "archiveSha256": "1" * 64, "baseCommit": "a" * 40, "classificationDigest": "2" * 64})
assert evidence["djangoCheck"] and evidence["passed"] and evidence["insertRolledBack"]
assert (pointer.read_bytes() if pointer.exists() else None) == pointer_before
from django.db import models, IntegrityError
class UnsafeLegacy(models.Model):
    value = models.TextField()
    class Meta:
        app_label = "compute"
        db_table = "release_unsafe_probe"
with connection.cursor() as cursor:
    cursor.execute("CREATE TABLE release_unsafe_probe (id INTEGER PRIMARY KEY AUTOINCREMENT, value TEXT NOT NULL, extra TEXT NOT NULL)")
try:
    smoke([UnsafeLegacy], connection)
except IntegrityError:
    pass
else:
    raise AssertionError("新增非空列没有数据库默认值时，兼容冒烟必须失败")
assert UnsafeLegacy.objects.count() == 0
print("旧代码列集 INSERT 成功；三个数据库默认值为空对象；makemigrations 无差异")
"""


def test_compute_0007_legacy_insert_and_makemigrations(tmp_path):
    raw = tomlkit.parse((ROOT / "config/app.test.toml").read_text())
    raw["application"]["storage"]["app_data"] = str(tmp_path / "app")
    raw["application"]["storage"]["research_data_root"] = str(tmp_path / "research")
    for name in ("app/database", "app/logs", "research"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    (tmp_path / "app/database/.secret_key").write_text("仅用于隔离测试的临时密钥")
    config = tmp_path / "app.toml"
    config.write_text(tomlkit.dumps(raw))
    done = subprocess.run(
        [PYTHON, "-c", SCRIPT, str(ROOT), str(config)],
        cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "makemigrations 无差异" in done.stdout
