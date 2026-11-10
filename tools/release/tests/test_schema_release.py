"""新增迁移的同包绑定、正式切换、数据库保留与回退证据。"""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sqlite3

import pytest

from tools.release import artifacts, candidate, compatibility, protocol, server

SQL = "ALTER TABLE marker ADD COLUMN extra TEXT NOT NULL DEFAULT '{}'"
MIGRATION = "backend/apps/app/migrations/0002_extra.py"


@pytest.fixture
def additive(layout, monkeypatch, tmp_path):
    path = layout.source / MIGRATION
    path.parent.mkdir(parents=True)
    path.write_text(
        "from django.db import migrations, models\nclass Migration(migrations.Migration):\n dependencies=[('app','0001_initial')]\n operations=[migrations.AddField(model_name='marker', name='extra', field=models.JSONField(default=dict, db_default={}))]\n"
    )
    release = layout.release
    release.update(
        mode="full", noSchemaChanges=False, files=artifacts.tree_files(layout.source)
    )
    layout.package = layout.package.with_name("release-additive.tar.gz")
    release["package"] = artifacts.write_package(
        release["files"],
        lambda name: (layout.source / name).read_bytes(),
        layout.package,
    )
    classification = artifacts.classify_migrations(
        release, release["rollbackFiles"], layout.source
    )
    copied = tmp_path / "expected/app/database/meta.db"
    copied.parent.mkdir(parents=True)
    server.backup_database(layout.config, copied)
    candidate_config = {**layout.config, "appData": str(copied.parent.parent)}
    before = server.applied_migrations(candidate_config)
    with sqlite3.connect(copied) as db:
        db.execute(SQL)
        db.execute("INSERT INTO django_migrations VALUES ('app', '0002_extra')")
    identity = server.database_state(candidate_config)
    legacy = {
        "passed": True,
        "djangoCheck": True,
        "read": True,
        "insertRolledBack": True,
        "archiveSha256": release["package"]["sha256"],
        "baseCommit": release["baseline"]["commit"],
        "classificationDigest": server.digest(classification),
    }
    receipt = artifacts.acceptance(release, {"candidateChecks": True})
    receipt["migrationEvidence"] = {
        "archiveSha256": release["package"]["sha256"],
        "classificationDigest": server.digest(classification),
        "databaseState": identity,
        "baselineAppliedMigrations": before,
        "compatibility": legacy,
    }
    release["candidateAcceptance"] = receipt
    server.write_json(layout.manifest, release)
    original = server.manage

    def manage(config, root, args, log):
        result = original(config, root, args, log)
        if args[0] == "showmigrations":
            text = "[X] app.0001_initial\n"
            if str(root) != str(layout.previous):
                done = ["app", "0002_extra"] in server.applied_migrations(config)
                text += ("[X]" if done else "[ ]") + " app.0002_extra\n"
            Path(log).write_text(text)
            return text
        if args[0] == "migrate":
            with sqlite3.connect(server.database(config)) as db:
                db.execute(SQL)
                db.execute("INSERT INTO django_migrations VALUES ('app', '0002_extra')")
        return result

    monkeypatch.setattr(server, "manage", manage)
    return layout


def stage(layout):
    release, package = server.load_release(
        layout.config, layout.manifest, server.sha(layout.manifest)
    )
    server.stage(layout.config, release, package)
    server.write_json(layout.target / "frozen-manifest.json", release)
    return release


@pytest.mark.parametrize(
    "target",
    [
        "classificationPackage",
        "classificationAllowed",
        "evidencePackage",
        "compatibilityPackage",
        "compatibilityFailed",
        "classificationDigest",
        "fingerprintDigest",
        "migrationRecords",
        "noSchemaLie",
    ],
)
def test_manifest_binding_rejects_missing_or_mismatched_evidence(additive, target):
    release = deepcopy(additive.release)
    evidence = release["candidateAcceptance"]["migrationEvidence"]
    if target == "classificationPackage":
        release["migrationClassification"]["archiveSha256"] = "0" * 64
    elif target == "classificationAllowed":
        release["migrationClassification"]["allowed"] = False
    elif target == "evidencePackage":
        evidence["archiveSha256"] = "0" * 64
    elif target == "compatibilityPackage":
        evidence["compatibility"]["archiveSha256"] = "0" * 64
    elif target == "compatibilityFailed":
        evidence["compatibility"]["passed"] = False
    elif target == "classificationDigest":
        evidence["classificationDigest"] = "0" * 64
    elif target == "fingerprintDigest":
        evidence["databaseState"]["fingerprint"]["sha256"] = "0" * 64
    elif target == "migrationRecords":
        evidence["databaseState"]["appliedMigrations"] = []
    else:
        release["noSchemaChanges"] = True
    server.write_json(additive.manifest, release)
    with pytest.raises(server.ReleaseError):
        server.load_release(
            additive.config, additive.manifest, server.sha(additive.manifest)
        )


def test_accepted_additive_cutover_and_explicit_code_rollback(additive):
    release = stage(additive)
    lock = {"retainDeployLock": False}
    server.cutover(additive.config, release, lock)
    accepted = json.loads((additive.target / "production-accepted.json").read_text())
    assert accepted["databaseAdvanced"] and Path(accepted["quiescedBackup"]).is_file()
    current = {
        **additive.config,
        "expectedPreviousRoot": release["appRoot"],
        "expectedLauncherSha256": server.sha(additive.config["launcher"]),
    }
    baseline = {**server.inspect(current), "commit": release["commit"]}
    ops = additive.target.parent / "rollback-additive"
    ops.mkdir()
    protocol.rollback(current, {"baseline": baseline}, ops, lock)
    receipt = json.loads((ops / "production-rolled-back.json").read_text())
    assert receipt["databaseAdvanced"] and not receipt["databaseRestored"]
    assert receipt["databaseHandling"] == "数据库结构已前进，旧代码经兼容检查可运行"
    server.verify_database_state(
        current, release["candidateAcceptance"]["migrationEvidence"]["databaseState"]
    )
    assert not lock["retainDeployLock"]


def test_health_failure_rolls_back_code_but_keeps_schema_and_backup_receipt(
    additive, monkeypatch
):
    release = stage(additive)

    def health(*args, **kwargs):
        if not kwargs.get("old"):
            raise server.ReleaseError("健康检查失败")

    monkeypatch.setattr(server, "wait_gate", health)
    lock = {"retainDeployLock": False}
    with pytest.raises(server.ReleaseError, match="rolled back"):
        server.cutover(additive.config, release, lock)
    receipt = json.loads((additive.target / "production-rolled-back.json").read_text())
    assert receipt["databaseAdvanced"] and not receipt["databaseRestored"]
    assert Path(receipt["quiescedBackup"]).is_file()
    with sqlite3.connect(server.database(additive.config)) as db:
        db.execute("INSERT INTO marker (value) VALUES ('旧代码列集')")
        assert db.execute(
            "SELECT extra FROM marker WHERE value='旧代码列集'"
        ).fetchone() == ("{}",)
    assert str(additive.previous) in Path(additive.config["launcher"]).read_text()
    assert not lock["retainDeployLock"]


@pytest.mark.parametrize("mutation", ["schema", "records", "failedMigrate"])
def test_unexpected_migration_state_retains_lock_and_never_starts_old(
    additive, monkeypatch, mutation
):
    release = stage(additive)
    original = server.manage

    def manage(config, root, args, log):
        result = original(config, root, args, log)
        if args[0] == "migrate":
            with sqlite3.connect(server.database(config)) as db:
                if mutation == "schema":
                    db.execute("CREATE INDEX unexpected ON marker(value)")
                else:
                    db.execute("DELETE FROM django_migrations WHERE name='0002_extra'")
            if mutation == "failedMigrate":
                raise server.ReleaseError("迁移失败")
        return result

    monkeypatch.setattr(server, "manage", manage)
    lock = {"retainDeployLock": False}
    with pytest.raises(server.ReleaseError, match="retained"):
        server.cutover(additive.config, release, lock)
    assert lock["retainDeployLock"]
    assert not any(event[0] == "start" for event in additive.state["events"])


def test_baseline_records_and_added_files_must_match(additive):
    release = stage(additive)
    with sqlite3.connect(server.database(additive.config)) as db:
        db.execute("INSERT INTO django_migrations VALUES ('unknown', '0001')")
    with pytest.raises(server.ReleaseError, match="已应用迁移"):
        server.migration_gate(additive.config, release)
    path = Path(release["appRoot"]) / MIGRATION
    path.write_text(path.read_text().replace("db_default={}", "default=dict"))
    with pytest.raises(server.ReleaseError, match="人工制定"):
        server.migration_sources_gate(release)


def test_fingerprint_ignores_data_but_tracks_defaults_indexes_and_constraints(layout):
    before = server.schema_fingerprint(layout.config)
    with sqlite3.connect(server.database(layout.config)) as db:
        db.execute("INSERT INTO marker VALUES ('数据不是结构')")
    assert before == server.schema_fingerprint(layout.config)
    with sqlite3.connect(server.database(layout.config)) as db:
        db.execute("CREATE UNIQUE INDEX marker_unique ON marker(value)")
    assert before != server.schema_fingerprint(layout.config)


@pytest.mark.parametrize(
    "column",
    [
        "value INTEGER",
        "value TEXT NOT NULL",
        "value TEXT DEFAULT '{}'",
        "value TEXT CHECK(value <> 'forbidden')",
        "value TEXT REFERENCES parent(id)",
    ],
)
def test_fingerprint_detects_column_and_constraint_changes(tmp_path, column):
    states = []
    for name, definition in (("old", "value TEXT"), ("new", column)):
        app = tmp_path / name
        (app / "database").mkdir(parents=True)
        with sqlite3.connect(app / "database/meta.db") as db:
            db.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
            db.execute("CREATE TABLE shape(" + definition + ")")
        states.append(
            server.schema_fingerprint({"appData": str(app), "sqliteSeconds": 10})
        )
    assert states[0] != states[1]


def test_candidate_rejects_legacy_compatibility_failure_before_workers(
    additive, monkeypatch, tmp_path
):
    production = Path(additive.config["productionConfig"])
    production.write_text(
        production.read_text() + '\n[compute]\nmode="native"\n[runtime]\n'
    )
    additive.release["baseline"]["configSha256"] = server.sha(production)
    ops = tmp_path / "candidate-ops"
    ops.mkdir()
    monkeypatch.setattr(
        compatibility,
        "run",
        lambda *args: (_ for _ in ()).throw(server.ReleaseError("旧代码兼容检查失败")),
    )
    with pytest.raises(server.ReleaseError, match="旧代码兼容"):
        candidate.run(
            additive.config,
            additive.release,
            additive.package,
            ops,
            {"port": 16744, "commandSeconds": 300},
        )
    assert not (ops / "candidate-accepted.json").exists()
    assert not any(event[0] in ("start", "stop") for event in additive.state["events"])


def test_explicit_rollback_rejects_unknown_advanced_structure(additive, monkeypatch):
    release = stage(additive)
    lock = {"retainDeployLock": False}
    server.cutover(additive.config, release, lock)
    current = {
        **additive.config,
        "expectedPreviousRoot": release["appRoot"],
        "expectedLauncherSha256": server.sha(additive.config["launcher"]),
    }
    baseline = {**server.inspect(current), "commit": release["commit"]}
    with sqlite3.connect(server.database(current)) as db:
        db.execute("CREATE TABLE unknown (value TEXT)")
    ops = additive.target.parent / "rollback-unknown"
    ops.mkdir()
    stopped = [event for event in additive.state["events"] if event[0] == "stop"]
    original_process = server.process
    monkeypatch.setattr(
        server,
        "process",
        lambda pid: (
            {"pid": pid, "startTicks": 1}
            if pid == os.getpid()
            else original_process(pid)
        ),
    )
    with pytest.raises(server.SchemaChanged):
        with protocol.guarded_publication(current, "a" * 64) as guarded:
            protocol.rollback(current, {"baseline": baseline}, ops, guarded)
    assert Path(current["deployLock"]).exists()
    assert stopped == [
        event for event in additive.state["events"] if event[0] == "stop"
    ]


def test_full_job_uses_same_package_candidate_evidence_before_switch(
    additive, monkeypatch
):
    ops = Path(additive.config["opsParent"]) / "20261111T000000Z-bbbbbbb-123abc"
    ops.mkdir(parents=True)
    release = additive.release
    tools = Path(server.__file__).parent
    release["package"]["file"] = "release-code.tar.gz"
    release["toolHashes"] = {
        name: server.sha(tools / name) for name in artifacts.TOOL_FILES
    }
    for name in artifacts.TOOL_FILES:
        shutil.copy2(tools / name, ops / name)
    shutil.copy2(additive.package, ops / "release-code.tar.gz")
    for name, value in (
        ("frozen-manifest.json", release),
        ("remote-config.json", additive.config),
        ("candidate-options.json", {}),
    ):
        server.write_json(ops / name, value)
    monkeypatch.setattr(candidate, "run", lambda *args: release["candidateAcceptance"])
    original_process = server.process
    monkeypatch.setattr(
        server,
        "process",
        lambda pid: (
            {"pid": pid, "startTicks": 1}
            if pid == os.getpid()
            else original_process(pid)
        ),
    )
    protocol.run_job(ops, server.sha(ops / "frozen-manifest.json"), "publish")
    accepted_manifest = json.loads((ops / "accepted-manifest.json").read_text())
    assert (
        accepted_manifest["candidateAcceptance"]["migrationEvidence"]
        == release["candidateAcceptance"]["migrationEvidence"]
    )
    assert (ops / "production-accepted.json").is_file()
    assert not Path(additive.config["deployLock"]).exists()
