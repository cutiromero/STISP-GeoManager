"""Grid admission reuses source metadata and retains ordinary input budgets."""

from copy import deepcopy

import pytest

from apps.compute.packages import ComputeError
from apps.compute.raster_contracts import gaps, validate_contract


def metadata():
    return {
        "rasterMetadata": {
            "bands": [{"type": "uint8"}] * 3,
            "size": [6144, 6144],
            "geoTransform": [0, 2, 0, 0, 0, -2],
            "linearUnitMeters": 1,
        }
    }


def test_original_grid_contract_and_separate_runtime_budgets():
    spec = {
        "key": "image",
        "raster": {
            "bandCount": 3,
            "dtypes": ["uint8"],
            "pixelSizeMeters": 2,
            "minSide": 1024,
            "northUp": True,
        },
    }
    info = metadata()
    assert gaps(spec, info, 150000000) == []
    assert gaps(spec, info, 100000000)
    for key, value in [
        ("linearUnitMeters", None),
        ("size", [32, 32]),
        ("geoTransform", [0, 2, 1, 0, 0, -2]),
        ("bands", [{"type": "float32"}]),
    ]:
        changed = deepcopy(info)
        changed["rasterMetadata"][key] = value
        assert gaps(spec, changed, 150000000)


@pytest.mark.parametrize(
    "contract",
    [
        {"dtypes": [[]]},
        {"bandCount": True},
        {"minSide": 0},
        {"pixelSizeMeters": float("nan")},
        {"northUp": 1},
        {"extra": 1},
    ],
)
def test_malformed_contract_is_a_validation_error(contract):
    with pytest.raises(ComputeError):
        validate_contract(contract)
