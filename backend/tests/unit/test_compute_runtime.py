import json
import sys
from types import SimpleNamespace

from apps.compute import runtime
from apps.compute.config import ComputeConfig


def native_config():
    return ComputeConfig(
        mode="native",
        interpreter=sys.executable,
        command=("docker",),
        image="geomanager-compute:1",
        memory_mb=2048,
        timeout_seconds=30,
        input_mb=1024,
        output_mb=1024,
        retention_days=7,
        user_queue=3,
        global_queue=20,
    )


def test_native_runtime_executes_runner_and_cleans_status(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "config", native_config)
    root = tmp_path / "compute"
    package = root / "algorithm"
    inputs = root / "inputs"
    outputs = root / "results"
    package.mkdir(parents=True)
    inputs.mkdir()
    outputs.mkdir()
    (package / "main.py").write_text(
        "def run(context):\n"
        "    context.output_path('result.csv').write_text('value\\n42\\n')\n",
        encoding="utf-8",
    )
    (inputs / "context.json").write_text(
        json.dumps({"inputs": {}, "parameters": {}}), encoding="utf-8"
    )
    state = runtime.inspect_runtime()
    assert state["ready"], state
    attempt = SimpleNamespace(runtime_digest=state["imageDigest"])
    runtime.execute(
        attempt,
        package,
        inputs,
        outputs,
        {"timeoutSeconds": 10, "outputs": [{"file": "result.csv"}]},
        lambda: None,
    )
    assert (outputs / "result.csv").read_text(encoding="utf-8") == "value\n42\n"
    assert not (outputs / "__platform_status.json").exists()
    assert not (root / ".runner.pid").exists()


def test_native_runtime_rejects_missing_dependency(monkeypatch):
    monkeypatch.setattr(runtime, "config", native_config)
    monkeypatch.setattr(
        runtime.importlib.metadata,
        "version",
        lambda package: (_ for _ in ()).throw(
            runtime.importlib.metadata.PackageNotFoundError(package)
        ),
    )
    state = runtime.inspect_runtime()
    assert not state["ready"]
