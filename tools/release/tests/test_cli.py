"""配置、默认离线与唯一连接执行器。"""

import json
from pathlib import Path
import subprocess

import pytest

from tools.release import artifacts, config as configuration, executor, release, server

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.toml"


@pytest.mark.parametrize(
    "replace_with",
    [
        ("port = 57865", ""),
        ("port = 57865", 'port = "57865"'),
        ('user = "root"', 'user = "root"\npassword = "not-a-real-password"'),
        ("drainSeconds = 900", "drainSeconds = 1"),
        ("maxArchiveBytes = 1073741824", "maxArchiveBytes = 1073741825"),
        ('"ConnectTimeout=15"', '"StrictHostKeyChecking=no"'),
        ('"ConnectTimeout=15"', '"ProxyCommand=sh -c unsafe"'),
        ('baseUrl = "http://127.0.0.1:6007"', 'baseUrl = "http://example.invalid"'),
        ('pnpm = ["pnpm",', "pnpm = [12,"),
        ('pnpm = ["pnpm",', 'pnpm = ["",'),
        ('"frontend/src/assets/team/han-yang.jpeg"', '"../outside.jpeg"'),
    ],
)
def test_config_missing_invalid(tmp_path, replace_with):
    path = tmp_path / "config.toml"
    path.write_text(EXAMPLE.read_text().replace(*replace_with))
    with pytest.raises(configuration.ConfigError):
        configuration.load(path)


def test_config_example_and_execution_placeholders():
    assert configuration.load(EXAMPLE)["local"]["branch"] == "codex/xintao"
    with pytest.raises(configuration.ConfigError, match="占位"):
        configuration.load(EXAMPLE, executing=True)


def test_release_and_fast_verification_share_pnpm_prefix(config):
    from scripts.verify_fast import PNPM

    assert tuple(config["local"]["pnpm"]) == PNPM


@pytest.mark.parametrize("command", ["inspect", "fast", "full", "status", "rollback"])
def test_default_plan_never_calls_ssh_or_scp(tmp_path, monkeypatch, capsys, command):
    path = tmp_path / "offline.toml"
    path.write_text(
        EXAMPLE.read_text().replace("101.42.12.157", "does-not-exist.invalid")
    )
    calls = []

    class Recorder(executor.Executor):
        def _run(self, command, **kwargs):
            calls.append(command)
            raise AssertionError("默认计划不能调用连接执行器")

    monkeypatch.setattr(artifacts, "commit_id", lambda *args: "a" * 40)
    monkeypatch.setattr(artifacts, "git", lambda *args, **kwargs: "codex/xintao")
    monkeypatch.setattr(artifacts, "untracked_files", lambda repo: ["local-image.jpeg"])
    assert (
        release.main([command, "--config", str(path)], executor_factory=Recorder) == 0
    )
    assert calls == []
    output = capsys.readouterr().out
    assert "不会连接" in output
    assert "local-image.jpeg" in output


def test_executor_defense_in_depth_without_execute(config, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: calls.append(args))
    runner = executor.Executor(config)
    runner.ssh(["echo", "not-run"])
    runner.upload("missing", "/remote/not-run")
    runner.origin_head(Path("/repo"), "codex/xintao")
    assert calls == []


def test_executor_key_only_and_command_quoting(config):
    commands = []

    class Recorder(executor.Executor):
        def _run(self, command, **kwargs):
            commands.append(command)
            return b""

    runner = Recorder(config, execute=True)
    runner.ssh(["/python", "-c", "print('space ; literal')"])
    runner.upload("/local/archive", "/safe/remote")
    for command in commands:
        for option in executor.AUTH_OPTIONS:
            assert option in command
        assert "StrictHostKeyChecking=no" not in command
    assert commands[0][-1].startswith("/python -c ")


@pytest.mark.parametrize("status", [" M tracked.py", "M  tracked.py", "A  added.py"])
def test_tracked_changes_block_preflight(monkeypatch, status):
    def git(repo, *args, **kwargs):
        assert args == ("status", "--porcelain", "--untracked-files=no")
        return status

    monkeypatch.setattr(artifacts, "git", git)
    with pytest.raises(server.ReleaseError, match="已跟踪文件不干净"):
        artifacts.preflight(Path("/repo"), "a" * 40, "codex/xintao")


def test_untracked_files_do_not_block_preflight_and_are_listed(monkeypatch):
    def git(repo, *args, **kwargs):
        if args[0] == "status":
            assert args[-1] == "--untracked-files=no"
            return ""
        if args[0] == "ls-files":
            assert kwargs["binary"] is True
            return "local.jpeg\0中文 图片.png\0".encode()
        if args[0] == "branch":
            return "codex/xintao"
        return "a" * 40

    monkeypatch.setattr(artifacts, "git", git)
    assert artifacts.preflight(Path("/repo"), "a" * 40, "codex/xintao") == [
        "local.jpeg",
        "中文 图片.png",
    ]


def test_local_only_records_untracked_files_and_resource_hashes(
    tmp_path, config, monkeypatch
):
    monkeypatch.setattr(release, "RECEIPTS", tmp_path / "records")
    monkeypatch.setattr(artifacts, "commit_id", lambda *args: "a" * 40)
    monkeypatch.setattr(artifacts, "diff_summary", lambda *args: {})
    monkeypatch.setattr(artifacts, "git_files", lambda *args: {})
    monkeypatch.setattr(server, "archive_files", lambda *args: {})
    monkeypatch.setattr(artifacts, "untracked_files", lambda repo: ["local.jpeg"])
    resources = {"local.jpeg": {"sha256": "b" * 64, "bytes": 1}}
    monkeypatch.setattr(
        artifacts,
        "package_source",
        lambda *args, **kwargs: {
            "timings": {},
            "package": {},
            "buildResources": resources,
        },
    )
    args = release.parse_args(
        [
            "fast",
            "--local-only",
            "--base-commit",
            "HEAD",
            "--baseline-package",
            str(tmp_path / "baseline.tar.gz"),
        ]
    )
    release.local_stages(args, config, tmp_path)
    record = next((tmp_path / "records").iterdir())
    for name in ("manifest.json", "receipt.json"):
        evidence = json.loads((record / name).read_text())
        assert evidence["untrackedFiles"] == ["local.jpeg"]
        assert evidence["buildResources"] == resources
        assert evidence["localOnly"] is True and evidence["deployable"] is False


def test_unpushed_head_refuses_before_any_server_read(config, monkeypatch):
    monkeypatch.setattr(artifacts, "commit_id", lambda *args: "a" * 40)
    monkeypatch.setattr(artifacts, "preflight", lambda *args: None)
    monkeypatch.setattr(
        release, "remote", lambda *args: pytest.fail("未推送提交不能连接正式服务器")
    )
    runner = type("Recorder", (), {"origin_head": lambda *args: "b" * 40})()
    args = release.parse_args(["fast", "--execute"])
    with pytest.raises(server.ReleaseError, match="origin"):
        release.publish(args, config, Path("/repo"), runner)
