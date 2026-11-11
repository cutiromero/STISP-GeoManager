import json
from pathlib import Path

import pytest

from tools.release import config as configuration, development, protocol, server


def test_development_backup_does_not_copy_database_or_static(layout, monkeypatch):
    config = {**layout.config, "developmentMode": True}
    monkeypatch.setattr(
        server, "backup_database", lambda *args: pytest.fail("开发发布不能复制整库")
    )
    destination = Path(config["releaseParent"]) / "temporary-release-config-backup"
    server.backup(config, destination)
    assert {path.name for path in destination.iterdir()} == {
        "app.toml",
        "launcher.sh",
        "hashes.json",
    }
    hashes = json.loads((destination / "hashes.json").read_text())
    assert set(hashes) == {"app.toml", "launcher.sh"}


def test_development_receipt_has_no_permanent_database_snapshot():
    receipt = server.database_receipt(
        {"noSchemaChanges": True}, "/temporary", {"developmentMode": True}
    )
    assert receipt["quiescedBackup"] is None
    assert receipt["databaseBackupCreated"] is False
    assert receipt["databaseRestored"] is False


def test_candidate_cleanup_preserves_diagnostics_and_source_originals(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(development, "require_inactive", lambda path: None)
    operations = tmp_path / "operations/run-1"
    candidate = operations / "candidate"
    for name in ("app", "research", "code"):
        (candidate / name).mkdir(parents=True)
        (candidate / name / "temporary-data").write_text("测试副本")
    (candidate / "hook.log").write_text("验收记录")
    original = tmp_path / "original-input.tif"
    original.write_text("原生数据")
    removed = development.cleanup_candidate(
        {"developmentMode": True, "opsParent": str(operations.parent)}, operations
    )
    assert len(removed) == 3
    assert original.read_text() == "原生数据"
    assert (candidate / "hook.log").is_file()
    assert not (candidate / "research").exists()


def test_cleanup_refuses_symlink_to_originals(tmp_path, monkeypatch):
    monkeypatch.setattr(development, "require_inactive", lambda path: None)
    originals = tmp_path / "originals"
    originals.mkdir()
    (originals / "user.tif").write_text("不能删除")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "research").symlink_to(originals, target_is_directory=True)
    with pytest.raises(server.ReleaseError, match="符号链接"):
        development.remove_owned(candidate / "research", candidate, [])
    assert (originals / "user.tif").read_text() == "不能删除"


def test_acceptance_keeps_current_release_and_removes_only_previous_program(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(development, "require_inactive", lambda path: None)
    old, new = tmp_path / "geomanager-release-old", tmp_path / "geomanager-release-new"
    for path in (old / "code", new / "code", new / "static-previous-active"):
        path.mkdir(parents=True)
        (path / "test-file").write_text("发布数据")
    originals = tmp_path / "research"
    originals.mkdir()
    (originals / "user.tif").write_text("用户原件")
    launcher = tmp_path / "launcher.sh"
    launcher.write_text("APP_ROOT=" + str(new / "code") + "\n")
    server.write_json(
        new / "production-accepted.json", {"accepted": True, "commit": "b" * 40}
    )
    operations = tmp_path / "operations/run-2"
    operations.mkdir(parents=True)
    (operations / "release-code.tar.gz").write_bytes(b"package")
    release = {
        "releaseDir": str(new),
        "appRoot": str(new / "code"),
        "commit": "b" * 40,
        "baseline": {"appRoot": str(old / "code")},
    }
    config = {
        "developmentMode": True,
        "releaseParent": str(tmp_path),
        "opsParent": str(operations.parent),
        "launcher": str(launcher),
    }
    report = development.prune_after_acceptance(config, release, operations)
    assert report["retainedCompiledVersions"] == 1
    assert not old.exists()
    assert (new / "code/test-file").is_file()
    assert (originals / "user.tif").read_text() == "用户原件"
    assert not (new / "static-previous-active").exists()
    assert not (operations / "release-code.tar.gz").exists()


def test_running_candidate_is_never_deleted(tmp_path, monkeypatch):
    operations = tmp_path / "operations/run-1"
    (operations / "candidate/research").mkdir(parents=True)
    (operations / "candidate/research/user.tif").write_text("测试用输入副本")

    def active(path):
        raise server.ReleaseError("目录仍被运行进程使用")

    monkeypatch.setattr(development, "require_inactive", active)
    with pytest.raises(server.ReleaseError, match="运行进程"):
        development.cleanup_candidate(
            {"developmentMode": True, "opsParent": str(operations.parent)}, operations
        )
    assert (operations / "candidate/research/user.tif").is_file()


def test_old_release_configs_default_to_non_development(tmp_path):
    example = Path(configuration.__file__).with_name("config.example.toml")
    path = tmp_path / "release.toml"
    path.write_text(example.read_text().replace("developmentMode = true\n", ""))
    assert configuration.load(path)["server"]["developmentMode"] is False


def test_development_recovery_requires_git_rebuild_instead_of_missing_old_directory(
    tmp_path,
):
    with pytest.raises(server.ReleaseError, match="GitHub"):
        protocol.rollback({"developmentMode": True}, {}, tmp_path, {})


def test_runtime_development_policy_cannot_be_published_with_old_backup_settings(
    layout,
):
    path = Path(layout.config["productionConfig"])
    path.write_text(path.read_text() + "\n[application.development]\nenabled = true\n")
    with pytest.raises(server.ReleaseError, match="developmentMode"):
        protocol.bind({**layout.config, "developmentMode": False})
    assert (
        protocol.bind({**layout.config, "developmentMode": True})["developmentMode"]
        is True
    )


def test_open_file_descriptor_blocks_directory_cleanup(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    descriptors = proc / "123/fd"
    descriptors.mkdir(parents=True)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "input.tif").write_text("仍被进程读取")
    (proc / "123/cwd").symlink_to(tmp_path, target_is_directory=True)
    (descriptors / "3").symlink_to(candidate / "input.tif")
    monkeypatch.setattr(development, "PROC_ROOT", proc)
    with pytest.raises(server.ReleaseError, match="运行进程"):
        development.require_inactive(candidate)
    assert (candidate / "input.tif").is_file()
