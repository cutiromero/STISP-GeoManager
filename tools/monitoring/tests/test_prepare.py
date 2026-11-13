import importlib.util
import json
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "prepare.py"
spec = importlib.util.spec_from_file_location("monitor_prepare", MODULE_PATH)
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


@pytest.fixture
def inputs(tmp_path):
    roots = {name: tmp_path / name for name in prepare.CODE_PATHS}
    files = []
    for name, root in roots.items():
        root.mkdir()
        path = root / "input.bin"
        path.write_bytes(b"original")
        files.append(
            {
                "dataset": name,
                "relative_path": "input.bin",
                "bytes": 8,
                "sha256": prepare.sha256(path),
            }
        )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"files": files}))
    receipt = tmp_path / "receipt.json"
    config = {
        "sources": {
            **{key: str(value) for key, value in roots.items()},
            "manifest": str(manifest),
            "receipt": str(receipt),
        },
        "verification": {
            "manifest_sha256": prepare.sha256(manifest),
            "archive_sha256": "a" * 64,
            "expected_files": 2,
            "expected_logical_bytes": 16,
            "hash_files_up_to_bytes": 1024,
            "inspect_geospatial_headers": False,
        },
        "scientific_contracts": {},
    }
    return config, roots, receipt


def write_receipt(inputs, **changes):
    config, roots, receipt = inputs
    value = {
        "complete": True,
        "archive_sha256": "a" * 64,
        "manifest_sha256": config["verification"]["manifest_sha256"],
        "files": 2,
        "logical_bytes": 16,
        "roots": {key: str(path) for key, path in roots.items()},
        **changes,
    }
    receipt.write_text(json.dumps(value))


def test_existing_files_without_full_restoration_receipt_do_not_become_ready(inputs):
    result = prepare.inspect(inputs[0])
    assert result["transferVerified"] is False
    assert all(scene["filesPresent"] for scene in result["scenes"].values())
    assert not any(scene["modelExecutable"] for scene in result["scenes"].values())


def test_verified_files_still_need_scientific_model_validation(inputs):
    write_receipt(inputs)
    result = prepare.inspect(inputs[0])
    assert result["transferVerified"] is True
    assert not any(scene["modelExecutable"] for scene in result["scenes"].values())


def test_small_file_hash_detects_same_size_content_changes(inputs):
    write_receipt(inputs)
    (inputs[1]["wildfire"] / "input.bin").write_bytes(b"modified")
    result = prepare.inspect(inputs[0])
    assert result["transferVerified"] is False
    assert result["scenes"]["wildfire"]["different"] == ["input.bin"]


@pytest.mark.parametrize(
    "changes",
    [{"complete": False}, {"files": 1}, {"archive_sha256": "b" * 64}, {"roots": {}}],
)
def test_incomplete_wrong_identity_or_unrelated_receipts_rejected(inputs, changes):
    write_receipt(inputs, **changes)
    assert prepare.inspect(inputs[0])["transferVerified"] is False


def test_partial_path_does_not_count_as_a_finished_file(inputs):
    root = inputs[1]["wildfire"]
    (root / "input.bin").rename(root / "input.bin.part")
    write_receipt(inputs)
    result = prepare.inspect(inputs[0])
    assert result["scenes"]["wildfire"]["missing"] == ["input.bin"]
    assert result["transferVerified"] is False


def test_manifest_is_authenticated_before_any_source_reads(inputs):
    config = inputs[0]
    Path(config["sources"]["manifest"]).write_text('{"files": []}')
    with pytest.raises(ValueError, match="SHA-256"):
        prepare.inspect(config)


def test_manifest_paths_cannot_escape_the_read_only_input_root(tmp_path):
    with pytest.raises(ValueError, match="越界"):
        prepare.safe_source(tmp_path, "../other")
    elsewhere = tmp_path.parent / "external"
    (tmp_path / "link").symlink_to(elsewhere)
    with pytest.raises(ValueError, match="越界"):
        prepare.safe_source(tmp_path, "link/data")
