"""固定服务器协议和切换会话回归。"""

import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from tools.release import artifacts, candidate, protocol, release, server


@pytest.fixture
def job(layout, monkeypatch):
    operations = Path(layout.config["opsParent"]) / "20261110T000000Z-bbbbbbb-123abc"
    operations.mkdir(mode=0o700, parents=True)
    tools = Path(server.__file__).parent
    for name in artifacts.TOOL_FILES:
        shutil.copy2(tools / name, operations / name)
    manifest = {
        **layout.release,
        "toolHashes": {name: server.sha(tools / name) for name in artifacts.TOOL_FILES},
    }
    server.write_json(operations / "frozen-manifest.json", manifest)
    server.write_json(operations / "remote-config.json", layout.config)
    server.write_json(operations / "candidate-options.json", {"port": 16744})
    shutil.copy2(layout.package, operations / "release-code.tar.gz")
    original_process = server.process

    def process(pid):
        if pid == os.getpid():
            return {"pid": pid, "startTicks": 123}
        return original_process(pid)

    monkeypatch.setattr(server, "process", process)
    return operations, manifest


def test_job_completes_and_scans_at_validation_boundaries(job, layout, monkeypatch):
    operations, manifest = job
    calls = []
    original_scan = server.archive_files

    def scan(path, limit):
        calls.append(str(path))
        return original_scan(path, limit)

    monkeypatch.setattr(server, "archive_files", scan)
    protocol.run_job(
        operations, server.sha(operations / "frozen-manifest.json"), "publish"
    )
    result = protocol.status(operations)
    assert (
        result["accepted"] is True and result["receipt"] == "production-accepted.json"
    )
    assert len(calls) == 2
    assert not Path(layout.config["deployLock"]).exists()
    assert json.loads((operations.parent / "latest.json").read_text())[
        "operations"
    ] == str(operations)


def test_launch_is_detached_does_not_unpack_or_repeat_archive_scan(
    job, layout, monkeypatch
):
    operations, manifest = job
    spawned = []

    def popen(command, **kwargs):
        spawned.append((command, kwargs))
        return SimpleNamespace(pid=12345)

    monkeypatch.setattr(protocol.subprocess, "Popen", popen)
    monkeypatch.setattr(server, "process", lambda pid: {"pid": pid, "startTicks": 999})
    monkeypatch.setattr(
        server, "archive_files", lambda *args: pytest.fail("启动入口不重复扫描大归档")
    )
    result = protocol.launch(
        operations, server.sha(operations / "frozen-manifest.json")
    )
    assert result["started"]
    assert spawned[0][1]["start_new_session"] is True
    assert spawned[0][1]["stdin"] == subprocess.DEVNULL
    assert "--execute" in spawned[0][0]
    assert not layout.target.exists()
    with pytest.raises(FileExistsError):
        protocol.launch(operations, server.sha(operations / "frozen-manifest.json"))


def test_full_candidate_exact_binding_before_stage(job, layout, monkeypatch):
    operations, manifest = job
    manifest["mode"] = "full"
    manifest.pop("preflightAcceptance")
    server.write_json(operations / "frozen-manifest.json", manifest)
    called = []

    def candidate_run(config, value, package, ops, options):
        assert not layout.target.exists()
        called.append(value["commit"])
        return artifacts.acceptance(value, {"genericCandidate": True})

    monkeypatch.setattr(candidate, "run", candidate_run)
    protocol.run_job(
        operations, server.sha(operations / "frozen-manifest.json"), "publish"
    )
    assert called == [manifest["commit"]]
    accepted_manifest = json.loads((operations / "accepted-manifest.json").read_text())
    assert (
        accepted_manifest["candidateAcceptance"]["archiveSha256"]
        == manifest["package"]["sha256"]
    )
    assert protocol.status(operations)["accepted"] is True


def test_candidate_unknown_process_retains_publication_lock(job, layout, monkeypatch):
    operations, manifest = job
    manifest["mode"] = "full"
    server.write_json(operations / "frozen-manifest.json", manifest)

    def fail(*args):
        raise server.UnknownStartedProcess(22222)

    monkeypatch.setattr(candidate, "run", fail)
    with pytest.raises(server.UnknownStartedProcess):
        protocol.run_job(
            operations, server.sha(operations / "frozen-manifest.json"), "publish"
        )
    assert Path(layout.config["deployLock"]).exists()
    assert protocol.status(operations)["retainDeployLock"] is True
    assert not layout.target.exists()


def test_wait_reconnects_but_never_relaunches(tmp_path, config, monkeypatch):
    launches = []
    polls = []

    class Recorder:
        def ssh(self, *args, **kwargs):
            launches.append(args)
            raise subprocess.TimeoutExpired("ssh", 1)

    def read(*args, **kwargs):
        polls.append(True)
        if len(polls) == 1:
            raise subprocess.TimeoutExpired("ssh", 1)
        return {"receipt": "production-accepted.json", "accepted": True}

    monkeypatch.setattr(release, "remote", read)
    monkeypatch.setattr(release.time, "sleep", lambda seconds: None)
    result = release.wait_job(Recorder(), config, "/remote/ops", "a" * 64, tmp_path)
    assert result["accepted"] is True
    assert len(launches) == 1 and len(polls) == 2


def test_known_remote_validation_failure_stops_without_polling(
    tmp_path, config, monkeypatch
):
    class Recorder:
        def ssh(self, *args, **kwargs):
            raise subprocess.CalledProcessError(1, "remote-validation")

    monkeypatch.setattr(
        release, "remote", lambda *args: pytest.fail("已知远端门禁失败不得继续轮询")
    )
    with pytest.raises(subprocess.CalledProcessError):
        release.wait_job(Recorder(), config, "/remote/ops", "a" * 64, tmp_path)


def test_full_schema_change_stops_after_candidate_before_production_stage(
    job, layout, monkeypatch
):
    operations, manifest = job
    manifest["mode"] = "full"
    manifest["noSchemaChanges"] = False
    server.write_json(operations / "frozen-manifest.json", manifest)
    monkeypatch.setattr(
        candidate,
        "run",
        lambda config, value, *args: artifacts.acceptance(
            value, {"candidateMigrations": True}
        ),
    )
    with pytest.raises(server.ReleaseError, match="without migration"):
        protocol.run_job(
            operations, server.sha(operations / "frozen-manifest.json"), "publish"
        )
    assert (operations / "accepted-manifest.json").is_file()
    assert not layout.target.exists()
    assert not any(event[0] == "stop" for event in layout.state["events"])
    assert not Path(layout.config["deployLock"]).exists()


def test_readonly_inspect_reports_missing_role_without_weakening_publish(
    layout, monkeypatch
):
    def fail(config):
        raise server.ReleaseError("Production must have exactly four verified roles")

    monkeypatch.setattr(server, "inspect", fail)
    states = {role: {"status": "missing", "processes": []} for role in server.ROLES}
    monkeypatch.setattr(protocol, "process_status", lambda *args: states)
    observed = protocol.describe(layout.config, strict=False)
    assert observed["baselineVerified"] is False
    assert observed["processStatus"]["web"]["status"] == "missing"
    assert observed["commit"] == "a" * 40
    assert observed["taskCounts"]["agent_agentrun"] == {"queued": 0, "running": 0}
    with pytest.raises(server.ReleaseError, match="four verified"):
        protocol.describe(layout.config)


def test_readonly_inspect_does_not_guess_missing_staged_commit(layout):
    (layout.previous.parent / "staged.json").unlink()
    observed = protocol.describe(layout.config, strict=False)
    assert observed["commit"] is None
    with pytest.raises(server.ReleaseError, match="staged.json"):
        protocol.describe(layout.config)
