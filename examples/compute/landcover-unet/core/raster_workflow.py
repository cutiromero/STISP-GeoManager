"""Streaming local land-cover raster composition."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()

CODES = {"farmland": 2, "forest": 4, "water": 5, "building": 6, "road": 8}
PRIORITY = ["building", "water", "farmland", "forest", "road"]
COLORS = {
    0: (0, 0, 0, 0),
    1: (255, 210, 102, 255),
    2: (255, 253, 91, 255),
    4: (39, 194, 35, 255),
    5: (121, 218, 255, 255),
    6: (255, 185, 185, 255),
    8: (243, 23, 23, 255),
    255: (0, 0, 0, 0),
}
CREATE_OPTIONS = [
    "TILED=YES",
    "BLOCKXSIZE=512",
    "BLOCKYSIZE=512",
    "COMPRESS=DEFLATE",
    "PREDICTOR=2",
    "BIGTIFF=IF_SAFER",
]


def grid_info(dataset: gdal.Dataset) -> dict:
    return {
        "width": dataset.RasterXSize,
        "height": dataset.RasterYSize,
        "transform": list(dataset.GetGeoTransform()),
        "projection": dataset.GetProjection(),
    }


def same_grid(left: gdal.Dataset, right: gdal.Dataset) -> bool:
    a, b = grid_info(left), grid_info(right)
    if (a["width"], a["height"]) != (b["width"], b["height"]):
        return False
    if not np.allclose(a["transform"], b["transform"], rtol=0, atol=1e-8):
        return False
    sa, sb = osr.SpatialReference(), osr.SpatialReference()
    sa.ImportFromWkt(a["projection"])
    sb.ImportFromWkt(b["projection"])
    return bool(sa.IsSame(sb))


def aligned(path: Path, reference: gdal.Dataset) -> gdal.Dataset:
    """Open an exact grid or a nearest-neighbour virtual view of it."""
    source = gdal.Open(str(path), gdal.GA_ReadOnly)
    if same_grid(source, reference):
        return source
    gt = reference.GetGeoTransform()
    if gt[2] or gt[4] or gt[1] <= 0 or gt[5] >= 0:
        raise ValueError("A north-up target grid is required for alignment")
    result = gdal.Warp(
        "",
        source,
        format="VRT",
        dstSRS=reference.GetProjection(),
        outputBounds=(
            gt[0],
            gt[3] + gt[5] * reference.RasterYSize,
            gt[0] + gt[1] * reference.RasterXSize,
            gt[3],
        ),
        width=reference.RasterXSize,
        height=reference.RasterYSize,
        resampleAlg="near",
        dstNodata=255,
    )
    if not same_grid(result, reference):
        raise ValueError(f"Failed to align raster: {path}")
    return result


def create_raster(path: Path, reference: gdal.Dataset) -> gdal.Dataset:
    result = gdal.GetDriverByName("GTiff").Create(
        str(path),
        reference.RasterXSize,
        reference.RasterYSize,
        1,
        gdal.GDT_Byte,
        options=CREATE_OPTIONS,
    )
    result.SetGeoTransform(reference.GetGeoTransform())
    result.SetProjection(reference.GetProjection())
    return result


def _rasterize_vector(
    path: Path, destination: Path, reference: gdal.Dataset
) -> gdal.Dataset:
    result = create_raster(destination, reference)
    result.GetRasterBand(1).Fill(0)
    vector = ogr.Open(str(path))
    if vector is None or vector.GetLayerCount() != 1:
        raise ValueError("Building supplement must contain one vector layer")
    layer = vector.GetLayer(0)
    if layer.GetSpatialRef() is None:
        raise ValueError("Building supplement has no coordinate reference")
    code = gdal.RasterizeLayer(result, [1], layer, burn_values=[1])
    if code != gdal.CE_None:
        raise RuntimeError("Building rasterization failed")
    result.FlushCache()
    return result


def compose(
    image: Path,
    masks: dict[str, Path],
    output: Path,
    classes: list[str] | None = None,
    mode: str = "complete",
    grid: Path | None = None,
    coverage: Path | None = None,
    building_vector: Path | None = None,
    priority: list[str] | None = None,
    progress: Callable[[str, float], None] | None = None,
) -> dict:
    """Compose selected binary predictions without loading an entire scene."""
    image, output = Path(image), Path(output)
    selected = list(CODES) if classes is None else list(classes)
    order = list(PRIORITY if priority is None else priority)
    if mode not in {"complete", "extract"}:
        raise ValueError("mode must be complete or extract")
    if (
        not selected
        or len(set(selected)) != len(selected)
        or set(selected) - CODES.keys()
    ):
        raise ValueError("Select distinct supported classes")
    if mode == "complete" and set(selected) != set(CODES):
        raise ValueError("Complete mode requires all five model classes")
    if (
        len(set(order)) != len(order)
        or set(order) - CODES.keys()
        or set(selected) - set(order)
    ):
        raise ValueError("Priority must contain every selected class exactly once")
    missing = set(selected) - masks.keys()
    if missing:
        raise ValueError(f"Missing binary masks: {sorted(missing)}")
    inputs = [image, Path(grid or image)] + [Path(masks[c]) for c in selected]
    inputs += [Path(p) for p in (coverage, building_vector) if p is not None]
    for path in inputs:
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.resolve() == output.resolve():
            raise ValueError("Output must differ from all inputs")
    partial = output.with_name(output.stem + ".partial.tif")
    supplement_path = output.with_name(output.stem + ".building.partial.tif")
    for path in (output, partial, supplement_path):
        if path.exists():
            raise FileExistsError(path)
    reference = gdal.Open(str(grid or image), gdal.GA_ReadOnly)
    image_ds = aligned(image, reference)
    sources = {c: aligned(Path(masks[c]), reference) for c in selected}
    for name, source in sources.items():
        if source.RasterCount != 1:
            raise ValueError(f"{name} must be a single-band binary mask")
        if source.GetRasterBand(1).GetNoDataValue() == 1:
            raise ValueError(f"Foreground value 1 is NoData in {name}")
    coverage_ds = aligned(Path(coverage), reference) if coverage else None
    output.parent.mkdir(parents=True, exist_ok=True)
    supplement = None
    if building_vector and "building" in selected:
        if progress:
            progress("building_supplement", 0.0)
        supplement = _rasterize_vector(
            Path(building_vector), supplement_path, reference
        )
    result = create_raster(partial, reference)
    result_band = result.GetRasterBand(1)
    result_band.SetNoDataValue(255)
    # TIFF photometric tags must be finalized before the first tile flush.
    table = gdal.ColorTable()
    for value, rgba in COLORS.items():
        table.SetColorEntry(value, rgba)
    result_band.SetColorTable(table)
    result_band.SetRasterColorInterpretation(gdal.GCI_PaletteIndex)
    result.SetMetadataItem("PRODUCT", "landcover")
    result.SetMetadataItem("SELECTED_CLASSES", ",".join(selected))
    if mode == "extract":
        old_internal_mask = gdal.GetConfigOption("GDAL_TIFF_INTERNAL_MASK")
        gdal.SetConfigOption("GDAL_TIFF_INTERNAL_MASK", "YES")
        result_band.CreateMaskBand(gdal.GMF_PER_DATASET)
        gdal.SetConfigOption("GDAL_TIFF_INTERNAL_MASK", old_internal_mask)
    counts = np.zeros(256, dtype=np.int64)
    width, height = reference.RasterXSize, reference.RasterYSize
    for y in range(0, height, 512):
        h = min(512, height - y)
        if coverage_ds:
            valid = coverage_ds.GetRasterBand(1).ReadAsArray(0, y, width, h) != 255
            valid &= (
                coverage_ds.GetRasterBand(1).GetMaskBand().ReadAsArray(0, y, width, h)
                > 0
            )
        else:
            bands = image_ds.ReadAsArray(
                0,
                y,
                width,
                h,
                band_list=list(range(1, min(3, image_ds.RasterCount) + 1)),
            )
            valid = np.any(bands != 0, axis=0) if bands.ndim == 3 else bands != 0
            valid &= (
                image_ds.GetRasterBand(1).GetMaskBand().ReadAsArray(0, y, width, h) > 0
            )
        values = np.full((h, width), 1 if mode == "complete" else 0, dtype=np.uint8)
        for name in reversed(order):
            if name not in selected:
                continue
            source_band = sources[name].GetRasterBand(1)
            array = source_band.ReadAsArray(0, y, width, h)
            allowed = {0, 1, 255}
            nodata = source_band.GetNoDataValue()
            if nodata is not None:
                allowed.add(nodata)
            if not np.isin(array, list(allowed)).all():
                raise ValueError(f"Mask {name} is not binary (0/1)")
            foreground = array == 1
            foreground &= source_band.GetMaskBand().ReadAsArray(0, y, width, h) > 0
            if name == "building" and supplement:
                foreground |= (
                    supplement.GetRasterBand(1).ReadAsArray(0, y, width, h) == 1
                )
            values[foreground & valid] = CODES[name]
        values[~valid] = 255
        result_band.WriteArray(values, 0, y)
        if mode == "extract":
            result_band.GetMaskBand().WriteArray(
                ((values != 0) & valid).astype(np.uint8) * 255, 0, y
            )
        counts += np.bincount(values.ravel(), minlength=256)
        if progress:
            progress("composing", min(1.0, (y + h) / height))
    result.FlushCache()
    levels = [
        level for level in (2, 4, 8, 16, 32, 64) if min(width, height) // level >= 1
    ]
    if progress:
        progress("overviews", 0.0)
    if levels:
        result.BuildOverviews("NEAREST", levels)
    result_band = result = None
    supplement = None
    sources.clear()
    image_ds = coverage_ds = None
    info = grid_info(reference)
    reference = None
    partial.replace(output)
    if supplement_path.exists():
        supplement_path.unlink()
    if progress:
        progress("completed", 1.0)
    return {
        "output": str(output.resolve()),
        "grid": info,
        "counts": {str(i): int(n) for i, n in enumerate(counts) if n},
        "classes": selected,
        "mode": mode,
    }
