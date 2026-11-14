"""GPU authority, frozen assets and file-evidence reuse without CUDA imports."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from apps.compute import gpu_runtime
from apps.compute.packages import ComputeError, validate_manifest


@pytest.fixture
def gpu(tmp_path, settings, monkeypatch):
    assets = tmp_path / "assets"
    (assets / "models").mkdir(parents=True)
    (assets / "config").mkdir()
    weights = []
    for name in ["building", "water", "forest", "farmland", "road"]:
        content = name.encode()
        (assets / "models" / (name + ".pth")).write_bytes(content)
        weights.append(
            {"file": name + ".pth", "sha256": hashlib.sha256(content).hexdigest()}
        )
    (assets / "models/model_manifest.json").write_text(json.dumps({"weights": weights}))
    for name in ["models", "postprocess"]:
        (assets / "config" / (name + ".json")).write_text("{}")
    python = tmp_path / "python"
    python.write_text("fixture")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "proj.db").write_text("fixture")
    path = tmp_path / "app.toml"
    path.write_text(f'''[compute]
mode="native"
[compute.gpu]
enabled=true
interpreter="{python}"
asset_root="{assets}"
proj_data="{proj}"
gdal_data="{tmp_path}"
lease_root="{tmp_path / "leases"}"
gpu_ids=[5,6]
project_ids=[2]
allowed_algorithms=["landcover-unet-infer"]
''')
    monkeypatch.setattr(settings, "PROJECT_CONFIG", SimpleNamespace(config_path=path))
    monkeypatch.setattr(
        gpu_runtime, "app_path", lambda *parts: tmp_path.joinpath("app", *parts)
    )
    monkeypatch.setattr(
        gpu_runtime,
        "environment",
        lambda _: {"python": "3.14", "packages": {"torch": "fixture"}},
    )
    return {
        "root": tmp_path,
        "assets": assets,
        "manifest": {
            "identifier": "landcover-unet-infer",
            "runtime": gpu_runtime.RUNTIME,
        },
    }


def test_gpu_profile_requires_project_and_registered_operator(gpu):
    with pytest.raises(ComputeError):
        gpu_runtime.binding(gpu["manifest"], 1)
    with pytest.raises(ComputeError):
        gpu_runtime.binding({**gpu["manifest"], "identifier": "other-model"}, 2)
    assert gpu_runtime.binding(gpu["manifest"], 2)[1]["ready"]


@pytest.mark.efficiency
def test_asset_hashes_are_reused_and_mutation_is_rejected(gpu, monkeypatch):
    original = hashlib.file_digest
    calls = []

    def calculate(stream, *args):
        calls.append(stream.name)
        return original(stream, *args)

    monkeypatch.setattr(hashlib, "file_digest", calculate)
    _, first = gpu_runtime.binding(gpu["manifest"], 2)
    assert len(calls) == 9
    _, second = gpu_runtime.binding(gpu["manifest"], 2)
    assert second["imageDigest"] == first["imageDigest"] and len(calls) == 9
    (gpu["assets"] / "models/water.pth").write_bytes(b"changed")
    with pytest.raises(ComputeError, match="摘要"):
        gpu_runtime.binding(gpu["manifest"], 2)


def test_gpu_lease_ignores_busy_cards_and_excludes_a_second_owner(gpu, monkeypatch):
    profile, _ = gpu_runtime.binding(gpu["manifest"], 2)
    monkeypatch.setattr(
        gpu_runtime.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            stdout="5, GPU-11111111-aaaa, 2000\n6, GPU-22222222-bbbb, 2\n"
        ),
    )
    with gpu_runtime.lease(profile) as device:
        assert device == "GPU-22222222-bbbb"
        with pytest.raises(ComputeError):
            with gpu_runtime.lease(profile):
                pass
    with gpu_runtime.lease(profile) as device:
        assert device == "GPU-22222222-bbbb"


def test_landcover_manifest_uses_registered_gpu_runtime():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    manifest = validate_manifest(
        json.loads((root / "examples/compute/landcover-unet/operator.yaml").read_text())
    )
    assert manifest["runtime"] == gpu_runtime.RUNTIME
    assert manifest["parameters"][0]["default"] == "all"
