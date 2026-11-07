"""Platform attestations skip duplicate raster reads without changing science hashes."""

import hashlib
from pathlib import Path
import runpy
import sys

import numpy as np
import rasterio

from apps.compute.input_versions import _raster_evidence
from tests.unit.test_geology_multi_algorithms import CORE, fixture


def test_verified_and_independently_read_inputs_have_identical_scientific_identity(
    tmp_path, monkeypatch
):
    sys.path.insert(0, str(CORE))
    from multi_io import inputs, settings

    original, _ = fixture(tmp_path)
    with rasterio.open(original.inputs["hematite"]) as stream:
        profile = {**stream.profile, "dtype": "float32", "nodata": None}
    weight = tmp_path / "hematite_weight.tif"
    with rasterio.open(weight, "w", **profile) as dst:
        dst.write(np.full((100, 100), 0.5, dtype="float32"), 1)
    original.inputs["hematite_weight"] = weight
    independent = inputs(original, settings(original))
    descriptors = {}
    for key, path in original.inputs.items():
        current = path.stat()
        with path.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        descriptors[key] = {
            "path": str(path),
            "sha256": checksum,
            "verifiedEvidence": {
                "schemaVersion": 1,
                "fileIdentity": [
                    current.st_ino,
                    current.st_size,
                    current.st_mtime_ns,
                    current.st_ctime_ns,
                    current.st_mode,
                ],
                "raster": _raster_evidence(path)
                if path.suffix == ".tif" and not key.endswith("_weight")
                else None,
            },
        }
    runner = runpy.run_path(
        str(Path(__file__).resolve().parents[3] / "deploy/compute/runner.py")
    )
    verified = runner["Context"](
        {"inputs": descriptors, "parameters": original.parameters}, tmp_path, tmp_path
    )
    monkeypatch.setattr(
        "multi_io.rasterio.open",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Duplicate pixel scan")
        ),
    )
    trusted = inputs(verified, settings(verified))
    assert independent[-1] == trusted[-1]
    assert independent[3:6] == trusted[3:6]
