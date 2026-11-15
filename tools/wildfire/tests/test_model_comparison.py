"""Scientific preprocessing must distinguish finite NoData, zero and land mask."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np

# CONFIGURATION
SOURCE = Path(__file__).resolve().parents[1] / "model_comparison.py"
SPEC = importlib.util.spec_from_file_location("wildfire_comparison", SOURCE)
comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparison)


def test_reader_masks_declared_finite_nodata_without_masking_zero():
    missing = np.float32(-3.4e38)
    reader = comparison.Reader.__new__(comparison.Reader)
    reader.metadata = {
        "pop_dens/.zarray": {"dtype": "<f4", "fill_value": float(missing)},
        "pop_dens/.zattrs": {"missing_value": float(missing)},
    }
    values = np.array([missing, 0, 123], dtype="<f4")
    reader.group = SimpleNamespace(
        OpenMDArray=lambda _: SimpleNamespace(Read=lambda **_: values.tobytes())
    )
    result = reader.read("pop_dens", [0], [3])
    assert np.isnan(result[0]) and result[1] == 0 and result[2] == 123


def test_normalization_fills_missing_after_scaling_and_preserves_land_mask():
    raw = np.full((1, 11, 2, 2), 2, dtype="float32")
    raw[:, :, 0, 0] = np.nan
    raw[:, -1] = np.array([[0, 0.25], [0.75, 1]])
    statistics = {
        name: {"mean": 2, "std": 2, "min": 0, "max": 4} for name in comparison.VARIABLES
    }
    result = comparison.normalize(raw, statistics, "standard_minus_one")
    assert np.all(result[:, :-1, 0, 0] == -1)
    assert np.all(result[:, :-1, 1, 1] == 0)
    np.testing.assert_array_equal(result[:, -1], raw[:, -1])
    assert np.isnan(raw[0, 0, 0, 0]) and raw[0, 0, 1, 1] == 2
