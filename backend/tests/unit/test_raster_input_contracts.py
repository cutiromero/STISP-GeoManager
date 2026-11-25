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


def test_full_native_grid_and_envi_band_order():
    from apps.compute.raster_windows import whole_grid_metadata

    contract = validate_contract(
        {"bandNames": ["B2", "B3", "B4", "B8"], "streaming": True}
    )
    source = metadata()
    source.update(sizeBytes=482241600, crs="EPSG:32645")
    grid = source["rasterMetadata"]
    grid["size"] = [10980, 10980]
    grid["bands"] = [
        {"description": f"{name} ({wave:.6f} Nanometers)", "type": "uint8"}
        for name, wave in zip(
            contract["bandNames"], [492.3, 559, 665, 833], strict=True
        )
    ]
    result = whole_grid_metadata(source)
    assert result["rasterWindow"] == [0, 0, 10980, 10980]
    assert result["rasterMetadata"] == grid
    assert 0 < result["sizeBytes"] < source["sizeBytes"]
    assert "rasterWindow" not in source
    assert gaps({"key": "image", "raster": contract}, result, 1_000_000) == []
    result["rasterMetadata"]["bands"].reverse()
    assert [
        row["code"]
        for row in gaps({"key": "image", "raster": contract}, result, 1_000_000)
    ] == ["RASTER_BAND_NAMES"]
