"""The display case uses an irregular island on the actual source pixel grid."""

from pathlib import Path
import runpy

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.affinity import translate

MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[3] / "scripts/geology_review_data.py")
)


def grid(path, crs=32646, transform=None):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=80,
        height=80,
        count=1,
        dtype="uint8",
        crs=crs,
        transform=transform or from_origin(767300.222, 3976400.912, 29, 29),
    ) as target:
        target.write(np.zeros((80, 80), dtype="uint8"), 1)
    return path


def test_natural_island_is_connected_irregular_and_native_grid_aligned(tmp_path):
    path = grid(tmp_path / "native.tif")
    original = path.read_bytes()
    gap, metadata = MODULE["natural_gap"](MODULE["CENTER"], path)
    repeated, again = MODULE["natural_gap"](MODULE["CENTER"], path)
    assert gap.equals_exact(repeated, 0) and metadata == again
    assert path.read_bytes() == original
    assert gap.geom_type == "Polygon" and gap.is_valid and not gap.interiors
    assert len(gap.exterior.coords) > 20 and gap.area < gap.envelope.area * 0.8
    assert metadata["gridCellSizeM"] == [29, 29]
    assert gap.area == pytest.approx(metadata["gridCellCount"] * 29 * 29)
    with rasterio.open(path) as source:
        for x, y in gap.exterior.coords:
            column, row = ~source.transform * (x, y)
            assert column == pytest.approx(round(column), abs=1e-8)
            assert row == pytest.approx(round(row), abs=1e-8)
    for (x1, y1), (x2, y2) in zip(gap.exterior.coords, list(gap.exterior.coords)[1:]):
        assert x1 == x2 or y1 == y2


def test_native_cell_offset_moves_the_island_without_changing_its_shape(tmp_path):
    path = grid(tmp_path / "native.tif")
    first, _ = MODULE["natural_gap"](MODULE["CENTER"], path)
    x, y = MODULE["CENTER"]
    moved, _ = MODULE["natural_gap"]((x + 58, y - 87), path)
    assert moved.equals(translate(first, xoff=58, yoff=-87))


def test_expanded_islands_have_distinct_shapes_and_sizes_on_the_native_grid(tmp_path):
    path = grid(tmp_path / "native.tif")
    islands = [
        MODULE["natural_gap"](MODULE["CENTER"], path, size, variant)[0]
        for size, variant in [((0.8, 1), 0), ((1, 0.85), 1), ((1.1, 1.1), 2)]
    ]
    assert len({island.area for island in islands}) == 3
    for island in islands:
        assert (
            island.is_valid and island.geom_type == "Polygon" and not island.interiors
        )
        assert island.area < 300000
        assert len(island.exterior.coords) > 20
        assert all(
            x1 == x2 or y1 == y2
            for (x1, y1), (x2, y2) in zip(
                island.exterior.coords, list(island.exterior.coords)[1:]
            )
        )


@pytest.mark.parametrize(
    "crs,transform",
    [
        (4326, None),
        (32646, rasterio.Affine(29, 1, 767300.222, 0, -29, 3976400.912)),
        (32646, from_origin(0, 1000, 29, 29)),
    ],
)
def test_invalid_or_unrelated_native_grid_is_rejected(tmp_path, crs, transform):
    path = grid(tmp_path / "invalid.tif", crs, transform)
    with pytest.raises(ValueError):
        MODULE["natural_gap"](MODULE["CENTER"], path)


def test_existing_output_is_preserved_instead_of_overwritten(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    original = output / "original.txt"
    original.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError, match="新的版本目录"):
        MODULE["prepare"](
            Path("unused"),
            Path("unused"),
            output,
            grid_reference=tmp_path / "native.tif",
        )
    assert original.read_text(encoding="utf-8") == "keep"
    assert list(output.iterdir()) == [original]


def test_preparation_requires_explicit_source_grid(tmp_path):
    output = tmp_path / "new"
    with pytest.raises(ValueError, match="格网参照"):
        MODULE["prepare"](Path("unused"), Path("unused"), output)
    assert not output.exists()


def test_existing_acceptance_material_is_preserved_before_creating_output(tmp_path):
    private = tmp_path / "acceptance-only"
    private.mkdir()
    original = private / "reference.txt"
    original.write_text("keep", encoding="utf-8")
    output = tmp_path / "new"
    with pytest.raises(FileExistsError, match="独立验收目录已有内容"):
        MODULE["prepare"](
            Path("unused"),
            Path("unused"),
            output,
            grid_reference=tmp_path / "native.tif",
        )
    assert original.read_text(encoding="utf-8") == "keep"
    assert not output.exists()
