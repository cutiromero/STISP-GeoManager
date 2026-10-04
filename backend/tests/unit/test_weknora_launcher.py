"""Process guard regressions; Linux process reads are replaced by explicit facts."""

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest


@pytest.fixture
def launcher(tmp_path):
    script = Path(__file__).resolve().parents[3] / "deploy/knowledge/ensure_weknora.py"
    spec = importlib.util.spec_from_file_location("tested_weknora_launcher", script)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"fcntl": SimpleNamespace()}):
        spec.loader.exec_module(module)
    root = tmp_path / "weknora"
    (root / "production").mkdir(parents=True)
    return module, root


def test_missing_pid_with_occupied_port_never_spawns_or_kills(launcher):
    module, root = launcher
    with (
        patch.object(module, "port_open", return_value=True),
        patch.object(module.subprocess, "Popen") as spawn,
        patch.object(module.os, "kill") as kill,
    ):
        with pytest.raises(module.LaunchError, match="occupied"):
            module.ensure(root, "production")
        spawn.assert_not_called()
        kill.assert_not_called()


def test_unrelated_recorded_pid_never_stops(launcher):
    module, root = launcher
    (root / "production/service.pid").write_text("123")
    with (
        patch.object(module, "alive", return_value=True),
        patch.object(module, "identity", return_value=False),
        patch.object(module.os, "kill") as kill,
    ):
        with pytest.raises(module.LaunchError, match="unrelated"):
            module.ensure(root, "production", stop=True)
        kill.assert_not_called()


def test_matching_pid_but_other_listener_never_trusts_health(launcher):
    module, root = launcher
    (root / "production/service.pid").write_text("123")
    with (
        patch.object(module, "alive", return_value=True),
        patch.object(module, "identity", return_value=True),
        patch.object(module, "port_open", return_value=True),
        patch.object(module, "owns_listener", return_value=False),
        patch.object(module, "healthy", return_value=True) as health,
    ):
        with pytest.raises(module.LaunchError, match="another process"):
            module.ensure(root, "production")
        health.assert_not_called()


def test_new_process_exit_cannot_be_masked_by_other_health_endpoint(launcher):
    module, root = launcher
    with (
        patch.object(module, "alive", return_value=False),
        patch.object(module, "healthy", return_value=True) as health,
    ):
        with pytest.raises(module.LaunchError, match="exited"):
            module.wait_ready(123, root, root / "production", 19020, 1)
        health.assert_not_called()


def test_own_ready_process_is_reused(launcher):
    module, root = launcher
    (root / "production/service.pid").write_text("123")
    with (
        patch.object(module, "alive", return_value=True),
        patch.object(module, "identity", return_value=True),
        patch.object(module, "port_open", return_value=True),
        patch.object(module, "owns_listener", return_value=True),
        patch.object(module, "healthy", return_value=True),
        patch.object(module.subprocess, "Popen") as spawn,
    ):
        result = module.ensure(root, "production")
        assert result["started"] is False and result["pid"] == 123
        spawn.assert_not_called()
