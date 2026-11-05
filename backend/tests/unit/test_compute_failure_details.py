"""Only bounded, allowlisted diagnostics cross the worker trust boundary."""

import json
import runpy
from types import SimpleNamespace

import pytest

from apps.compute import runtime
from apps.compute.packages import ComputeError
from tests.unit.test_compute_runtime import native_config

RUNNER = runtime.settings.PROGRAM_ROOT / "deploy/compute/runner.py"


def test_runner_redacts_arbitrary_exception_text_and_bounds_status():
    details = runpy.run_path(str(RUNNER))["failure_details"]
    memory_error = type("_ArrayMemoryError", (MemoryError,), {})
    cases = [
        (
            memory_error("Unable to allocate 25.9 MiB for shape (1,) password=secret"),
            "内存不足：无法分配 25.9 MiB",
        ),
        (
            ValueError("token=secret https://user:password@example.org /private/key"),
            "输入或参数校验失败",
        ),
        (RuntimeError("secret" * 10000), "算法执行异常"),
        (MemoryError(), "内存不足"),
    ]
    for error, expected in cases:
        status = {"status": "failed", **details(error)}
        assert status["error_detail"] == expected
        encoded = json.dumps(status).encode()
        assert len(encoded) <= 4096
        assert b"secret" not in encoded
        assert expected in runtime._failure_message(status)
    assert "secret" not in runtime._failure_message(
        {"error_type": "ValueError", "error_detail": "secret"}
    )
    assert "secret" not in runtime._failure_message(
        {"error_type": "secret<script>", "error_detail": "内存不足"}
    )


def test_native_failure_reaches_platform_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "config", native_config)
    package, inputs, output = [
        tmp_path / name for name in ("algorithm", "inputs", "output")
    ]
    for directory in (package, inputs, output):
        directory.mkdir()
    (inputs / "context.json").write_text(json.dumps({"inputs": {}, "parameters": {}}))
    (package / "main.py").write_text(
        "def run(context):\n"
        "    class _ArrayMemoryError(MemoryError): pass\n"
        "    raise _ArrayMemoryError('Unable to allocate 25.9 MiB password=secret')\n"
    )
    state = runtime.inspect_runtime()
    with pytest.raises(
        ComputeError, match="内存不足：无法分配 25.9 MiB（_ArrayMemoryError）"
    ) as failure:
        runtime.execute(
            SimpleNamespace(runtime_digest=state["imageDigest"]),
            package,
            inputs,
            output,
            {"timeoutSeconds": 10, "outputs": []},
            lambda: None,
        )
    assert "secret" not in str(failure.value)
    assert not (output / "__platform_status.json").exists()


def test_container_failure_uses_same_bounded_diagnostic(tmp_path, monkeypatch):
    config = native_config()
    from dataclasses import replace

    monkeypatch.setattr(runtime, "config", lambda: replace(config, mode="docker"))
    monkeypatch.setattr(runtime, "inspect_runtime", lambda: {"ready": True})
    calls = []

    def command(*args, **kwargs):
        calls.append(args)
        if args[0] == "exec":
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "status": "failed",
                        "error_type": "_ArrayMemoryError",
                        "error_detail": "内存不足：无法分配 25.9 MiB",
                    }
                ).encode(),
            )
        return SimpleNamespace(returncode=0, stdout=b"container")

    monkeypatch.setattr(runtime, "command", command)
    attempt = SimpleNamespace(
        runtime_digest="sha256:" + "a" * 64, container_name="gm-compute-" + "b" * 32
    )
    with pytest.raises(ComputeError, match="内存不足：无法分配 25.9 MiB"):
        runtime.execute(
            attempt,
            tmp_path,
            tmp_path,
            tmp_path,
            {"timeoutSeconds": 10, "outputs": []},
            lambda: None,
        )
    assert any(
        args[:4] == ("exec", attempt.container_name, "head", "-c") and args[4] == "4097"
        for args in calls
    )
    assert any(args[:2] == ("rm", "-f") for args in calls)
