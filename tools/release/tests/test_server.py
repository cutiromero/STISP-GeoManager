"""在本机临时目录演练解包、双锁、切换、自动恢复和显式回退。"""

import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from tools.release import candidate, protocol, server


def staged(layout):
    release, package = server.load_release(
        layout.config, layout.manifest, server.sha(layout.manifest)
    )
    server.stage(layout.config, release, package)
    server.write_json(layout.target / "frozen-manifest.json", release)
    return release


def test_stage_cutover_backup_launcher_and_explicit_rollback(layout):
    before_launcher = Path(layout.config["launcher"]).read_bytes()
    before_database = server.sha(server.database(layout.config))
    release = staged(layout)
    server.verify_tree(release["appRoot"], release["files"])
    with pytest.raises(FileExistsError):
        server.stage(layout.config, release, layout.package)
    lock = {"retainDeployLock": False}
    server.cutover(layout.config, release, lock)
    accepted = json.loads((layout.target / "production-accepted.json").read_text())
    assert accepted["accepted"] is True
    assert not lock["retainDeployLock"]
    launcher = Path(layout.config["launcher"]).read_text()
    assert f"APP_ROOT={release['appRoot']}\n" in launcher
    assert f"WORKER_APP_ROOT={release['appRoot']}\n" in launcher
    backup = Path(accepted["backup"])
    assert (backup / "meta.db").is_file()
    assert (backup / "meta-quiesced.db").is_file()
    assert (backup / "launcher.sh").read_bytes() == before_launcher
    assert server.sha(server.database(layout.config)) == before_database
    events = layout.state["events"]
    assert (
        len(
            [
                event
                for event in events
                if event[:1] == ("manage",) and event[1][0] == "archive_frontend_assets"
            ]
        )
        == 2
    )
    assert [event[1] for event in events if event[:1] == ("start",)] == [
        *server.ROLES[1:],
        "web",
    ]
    current = {
        **layout.config,
        "expectedPreviousRoot": release["appRoot"],
        "expectedLauncherSha256": server.sha(layout.config["launcher"]),
    }
    observation = {**server.inspect(current), "commit": release["commit"]}
    operations = layout.target.parent / "rollback-operations"
    operations.mkdir()
    protocol.rollback(current, {"baseline": observation}, operations, lock)
    result = json.loads((operations / "production-rolled-back.json").read_text())
    assert result["rolledBack"] is True and result["databaseRestored"] is False
    assert Path(layout.config["launcher"]).read_bytes() == before_launcher
    assert (Path(layout.config["appData"]) / "static/assets/old.js").is_file()
    assert server.sha(server.database(layout.config)) == before_database


def test_failed_health_automatically_restores_without_database_restore(
    layout, monkeypatch
):
    release = staged(layout)
    launcher = Path(layout.config["launcher"]).read_bytes()
    database = server.sha(server.database(layout.config))
    observed = []

    def health(*args, old=False):
        observed.append(old)
        if not old:
            raise server.ReleaseError("新代码健康门禁失败")

    monkeypatch.setattr(server, "wait_gate", health)
    lock = {"retainDeployLock": False}
    with pytest.raises(server.ReleaseError, match="rolled back"):
        server.cutover(layout.config, release, lock)
    assert observed == [False, True]
    assert Path(layout.config["launcher"]).read_bytes() == launcher
    assert server.sha(server.database(layout.config)) == database
    assert (layout.target / "production-rolled-back.json").is_file()
    assert not lock["retainDeployLock"]


def test_schema_mutation_retains_lock_and_never_restarts_old(layout, monkeypatch):
    release = staged(layout)
    original_manage = server.manage

    def manage(config, root, args, log):
        if args[0] == "migrate":
            with sqlite3.connect(server.database(config)) as database:
                database.execute("CREATE TABLE unexpected_schema(value TEXT)")
        return original_manage(config, root, args, log)

    monkeypatch.setattr(server, "manage", manage)
    lock = {"retainDeployLock": False}
    with pytest.raises(server.ReleaseError, match="retained"):
        server.cutover(layout.config, release, lock)
    assert lock["retainDeployLock"]
    assert not any(event[0] == "start" for event in layout.state["events"])
    assert (layout.target / "manual-intervention-required.json").is_file()


def test_baseline_and_migration_changes_fail_before_stopping(layout):
    release = staged(layout)
    migrations = Path(release["appRoot"]) / "backend/apps/sample/migrations"
    migrations.mkdir(parents=True)
    (migrations / "0002_changed.py").write_text("changed = True\n")
    with pytest.raises(server.ReleaseError, match="Migration sources"):
        server.migration_gate(layout.config, release)
    Path(layout.config["launcher"]).write_text("unexpected launcher")
    with pytest.raises(server.ReleaseError):
        server.baseline_gate(layout.config, release)
    assert not any(event[0] == "stop" for event in layout.state["events"])


def test_publication_locks_refuse_stale_and_retain_manual(tmp_path, monkeypatch):
    config = {
        "deployLock": str(tmp_path / "DEPLOY.lock"),
        "publishLock": str(tmp_path / "publish.lock"),
    }
    monkeypatch.setattr(server, "process", lambda pid: {"pid": pid, "startTicks": 123})
    with server.publication_locks(config, "a" * 64):
        with pytest.raises(FileExistsError):
            with server.publication_locks(config, "b" * 64):
                pass
    assert not Path(config["deployLock"]).exists()
    with server.publication_locks(config, "a" * 64) as state:
        state["retainDeployLock"] = True
    assert Path(config["deployLock"]).exists()
    with pytest.raises(FileExistsError):
        with server.publication_locks(config, "b" * 64):
            pass


def test_status_detects_pid_reuse(tmp_path, monkeypatch):
    server.write_json(
        tmp_path / "run.json", {"pid": 123, "identity": {"pid": 123, "startTicks": 1}}
    )
    monkeypatch.setattr(server, "process", lambda pid: {"pid": pid, "startTicks": 2})
    assert protocol.status(tmp_path)["receipt"] == "manual-intervention-required.json"


def test_content_type_rejects_html(monkeypatch):
    class Response:
        status = 200
        headers = SimpleNamespace(get_content_type=lambda: "text/html")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"fake-js"

    monkeypatch.setattr(
        server,
        "build_opener",
        lambda *args: SimpleNamespace(open=lambda *args, **kwargs: Response()),
    )
    with pytest.raises(server.ReleaseError, match="Content-Type"):
        server.http(
            {"baseUrl": "http://127.0.0.1:6007", "httpSeconds": 10}, "/static/a.js"
        )


def test_candidate_config_cannot_overlap_or_change_native_policy(tmp_path):
    raw = {
        "application": {
            "storage": {
                "app_data": str(tmp_path / "prod/app"),
                "research_data_root": str(tmp_path / "prod/research"),
            }
        },
        "compute": {"mode": "native"},
        "runtime": {},
    }
    result = candidate.isolated_config(raw, tmp_path / "candidate", 16744)
    assert result["runtime"]["disable_catalog_startup_scan"]
    assert result["runtime"]["disable_raster_startup_scan"]
    result["compute"]["mode"] = "docker"
    with pytest.raises(server.ReleaseError):
        candidate.isolated_config(result, tmp_path / "other", 16744)


def test_explicit_rollback_rejects_modified_old_static_before_stopping(layout):
    release = staged(layout)
    lock = {"retainDeployLock": False}
    server.cutover(layout.config, release, lock)
    (layout.target / "static-previous-active/assets/old.js").write_text("tampered")
    current = {
        **layout.config,
        "expectedPreviousRoot": release["appRoot"],
        "expectedLauncherSha256": server.sha(layout.config["launcher"]),
    }
    baseline = {**server.inspect(current), "commit": release["commit"]}
    ops = layout.target.parent / "rollback-corrupted"
    ops.mkdir()
    before = list(layout.state["events"])
    with pytest.raises(server.ReleaseError, match="旧前端静态文件摘要"):
        protocol.rollback(current, {"baseline": baseline}, ops, lock)
    assert [event for event in layout.state["events"] if event[0] == "stop"] == [
        event for event in before if event[0] == "stop"
    ]
