"""CPU model permissions, frozen weights and bounded concurrency."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from apps.compute import ml_runtime, model_runtime
from apps.compute.packages import ComputeError


@pytest.fixture
def runtime(settings, tmp_path, monkeypatch):
    assets = tmp_path / "models"
    assets.mkdir()
    model = assets / "forest.pkl"
    model.write_bytes(b"verified model")
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    profile = {
        "enabled": True,
        "asset_root": str(assets),
        "model_file": "forest.pkl",
        "model_sha256": digest,
        "project_ids": [13],
        "allowed_algorithms": ["spartina-rf-infer"],
        "proj_data": str(tmp_path),
        "gdal_data": str(tmp_path),
    }
    config = tmp_path / "app.toml"
    config.write_text(
        '[compute]\nmode="native"\n[compute.ml]\n'
        + "\n".join(key + "=" + json.dumps(value) for key, value in profile.items())
        + "\n"
    )
    settings.PROJECT_CONFIG = SimpleNamespace(
        config_path=config, app_data=tmp_path / "app"
    )
    monkeypatch.setattr(ml_runtime.importlib.metadata, "version", lambda _: "1.9.1")
    return model, {"runtime": ml_runtime.RUNTIME, "identifier": "spartina-rf-infer"}


def test_cpu_runtime_respects_project_and_weight_identity(runtime):
    model, manifest = runtime
    with pytest.raises(ComputeError):
        ml_runtime.binding(manifest, 2)
    profile, state = model_runtime.binding(manifest, 13)
    assert (
        state["ready"]
        and model_runtime.inspect(manifest, 13)["imageDigest"] == state["imageDigest"]
    )
    with model_runtime.lease(profile):
        with pytest.raises(ComputeError):
            with model_runtime.lease(profile):
                pass
    model.write_bytes(b"changed")
    with pytest.raises(ComputeError):
        ml_runtime.binding(manifest, 13)
