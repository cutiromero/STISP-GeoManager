"""Global component filtering and area-limited interior-hole filling."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
import time
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr, osr
from scipy.ndimage import binary_dilation

from raster_workflow import CREATE_OPTIONS, create_raster

gdal.UseExceptions()
ogr.UseExceptions()


def _units(source: gdal.Dataset) -> float:
    spatial_ref = osr.SpatialReference()
    spatial_ref.ImportFromWkt(source.GetProjection())
    if not spatial_ref.IsProjected():
        raise ValueError("Area thresholds require a projected coordinate reference")
    gt = source.GetGeoTransform()
    if gt[2] or gt[4] or gt[1] <= 0 or gt[5] >= 0:
        raise ValueError("Postprocessing requires a north-up raster")
    return float(spatial_ref.GetLinearUnits())


def _geometry_mask(
    geometry: ogr.Geometry, source: gdal.Dataset, halo: int = 1
) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    gt = source.GetGeoTransform()
    xmin, xmax, ymin, ymax = geometry.GetEnvelope()
    x0 = max(0, math.floor((xmin - gt[0]) / gt[1]) - halo)
    x1 = min(source.RasterXSize, math.ceil((xmax - gt[0]) / gt[1]) + halo)
    y0 = max(0, math.floor((ymax - gt[3]) / gt[5]) - halo)
    y1 = min(source.RasterYSize, math.ceil((ymin - gt[3]) / gt[5]) + halo)
    width, height = x1 - x0, y1 - y0
    raster = gdal.GetDriverByName("MEM").Create("", width, height, 1, gdal.GDT_Byte)
    raster.SetGeoTransform((gt[0] + x0 * gt[1], gt[1], 0, gt[3] + y0 * gt[5], 0, gt[5]))
    raster.SetProjection(source.GetProjection())
    vectors = ogr.GetDriverByName("Memory").CreateDataSource("")
    spatial_ref = osr.SpatialReference()
    spatial_ref.ImportFromWkt(source.GetProjection())
    layer = vectors.CreateLayer("item", srs=spatial_ref, geom_type=ogr.wkbUnknown)
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetGeometry(geometry)
    layer.CreateFeature(feature)
    gdal.RasterizeLayer(raster, [1], layer, burn_values=[1])
    array = raster.ReadAsArray().astype(bool)
    return array, (x0, y0, width, height)


def _near_invalid(
    geometry: ogr.Geometry, normalized: gdal.Dataset, has_invalid: bool, dilate: bool
) -> bool:
    if not has_invalid:
        return False
    mask, window = _geometry_mask(geometry, normalized)
    if dilate:
        mask = binary_dilation(mask, structure=np.ones((3, 3), dtype=bool))
    valid = normalized.GetRasterBand(2).ReadAsArray(*window) > 0
    return bool(np.any(mask & ~valid))


def _on_border(geometry: ogr.Geometry, source: gdal.Dataset) -> bool:
    xmin, xmax, ymin, ymax = geometry.GetEnvelope()
    gt = source.GetGeoTransform()
    tolerance = max(gt[1], -gt[5]) * 1e-6
    return (
        xmin <= gt[0] + tolerance
        or xmax >= gt[0] + source.RasterXSize * gt[1] - tolerance
        or ymax >= gt[3] - tolerance
        or ymin <= gt[3] + source.RasterYSize * gt[5] + tolerance
    )


def _fill_holes(
    geometry: ogr.Geometry,
    limit: float,
    unit: float,
    normalized: gdal.Dataset,
    has_invalid: bool,
) -> tuple[ogr.Geometry, int]:
    if not limit or geometry.GetGeometryType() not in (
        ogr.wkbPolygon,
        ogr.wkbPolygon25D,
    ):
        return geometry.Clone(), 0
    result = ogr.Geometry(ogr.wkbPolygon)
    result.AddGeometry(geometry.GetGeometryRef(0))
    filled = 0
    for index in range(1, geometry.GetGeometryCount()):
        ring = geometry.GetGeometryRef(index)
        hole = ogr.Geometry(ogr.wkbPolygon)
        hole.AddGeometry(ring)
        if hole.GetArea() * unit * unit <= limit and not _near_invalid(
            hole, normalized, has_invalid, dilate=False
        ):
            filled += 1
        else:
            result.AddGeometry(ring)
    return result, filled


def process_mask(
    input_path: Path,
    output_path: Path,
    min_area_m2: float = 0,
    max_hole_area_m2: float = 0,
    road_length_m: float = 0,
    preserve_border: bool = True,
    connectivity: int = 8,
) -> dict:
    """Filter whole-scene components, retaining image/NoData-edge components.

    A positive road length applies an AND rule with the area threshold.
    Zero-valued background remains valid even when a legacy mask labels it
    NoData; an explicit nonzero NoData value or dataset mask defines invalidity.
    """
    input_path, output_path = Path(input_path), Path(output_path)
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    if input_path.resolve() == output_path.resolve():
        raise ValueError("Input and output must differ")
    partial = output_path.with_name(output_path.stem + ".partial.tif")
    if output_path.exists() or partial.exists():
        raise FileExistsError(output_path if output_path.exists() else partial)
    if min(min_area_m2, max_hole_area_m2, road_length_m) < 0 or connectivity not in (
        4,
        8,
    ):
        raise ValueError("Thresholds must be nonnegative and connectivity 4 or 8")
    # Bound the shared raster-block cache before creating any temporary grids.
    gdal.SetCacheMax(min(gdal.GetCacheMax(), 256 * 1024 * 1024))
    source = gdal.Open(str(input_path), gdal.GA_ReadOnly)
    if source.RasterCount != 1:
        raise ValueError("Expected a single-band binary raster")
    unit = _units(source)
    band = source.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    if nodata == 1:
        raise ValueError("Foreground value 1 cannot be NoData")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "input_pixels": 0,
        "output_pixels": 0,
        "invalid_pixels": 0,
        "components": 0,
        "removed_components": 0,
        "filled_holes": 0,
    }
    with tempfile.TemporaryDirectory(
        prefix="landcover_components_", dir=output_path.parent
    ) as temporary:
        work = Path(temporary).resolve()
        if work.parent != output_path.parent.resolve():
            raise RuntimeError("Unexpected temporary directory")
        normalized = gdal.GetDriverByName("GTiff").Create(
            str(work / "normalized.tif"),
            source.RasterXSize,
            source.RasterYSize,
            2,
            gdal.GDT_Byte,
            options=CREATE_OPTIONS,
        )
        normalized.SetGeoTransform(source.GetGeoTransform())
        normalized.SetProjection(source.GetProjection())
        for y in range(0, source.RasterYSize, 512):
            h = min(512, source.RasterYSize - y)
            array = band.ReadAsArray(0, y, source.RasterXSize, h)
            allowed = [0, 1] + ([nodata] if nodata is not None else [])
            if not np.isin(array, allowed).all():
                raise ValueError("Input is not a binary 0/1 mask")
            valid = np.ones(array.shape, dtype=bool)
            if nodata is not None and nodata != 0:
                valid &= array != nodata
            if band.GetMaskFlags() & gdal.GMF_PER_DATASET:
                valid &= band.GetMaskBand().ReadAsArray(0, y, source.RasterXSize, h) > 0
            foreground = (array == 1) & valid
            normalized.GetRasterBand(1).WriteArray(foreground.astype(np.uint8), 0, y)
            normalized.GetRasterBand(2).WriteArray(valid.astype(np.uint8), 0, y)
            summary["input_pixels"] += int(foreground.sum())
            summary["invalid_pixels"] += int((~valid).sum())
        normalized.FlushCache()
        # Release the write-side block cache before the scanline-based operation.
        normalized = None
        normalized = gdal.Open(str(work / "normalized.tif"), gdal.GA_ReadOnly)
        result = create_raster(partial, source)
        result.GetRasterBand(1).SetNoDataValue(255)
        if min_area_m2 or max_hole_area_m2:
            spatial_ref = osr.SpatialReference()
            spatial_ref.ImportFromWkt(source.GetProjection())
            vectors = ogr.GetDriverByName("GPKG").CreateDataSource(
                str(work / "components.gpkg")
            )
            layer = vectors.CreateLayer(
                "components",
                srs=spatial_ref,
                geom_type=ogr.wkbPolygon,
                options=["SPATIAL_INDEX=NO"],
            )
            layer.CreateField(ogr.FieldDefn("value", ogr.OFTInteger))
            options = ["8CONNECTED=8"] if connectivity == 8 else []
            started = time.perf_counter()
            last_progress = [-1]

            def progress(complete: float, _message: str, _data: object) -> int:
                step = int(complete * 100) // 10
                if step > last_progress[0]:
                    last_progress[0] = step
                    print(
                        f"Polygonize {input_path.name}: {step * 10}% "
                        f"({time.perf_counter() - started:.1f}s)",
                        flush=True,
                    )
                return 1

            layer.StartTransaction()
            gdal.Polygonize(
                normalized.GetRasterBand(1),
                normalized.GetRasterBand(1),
                layer,
                0,
                options,
                callback=progress,
            )
            layer.CommitTransaction()
            kept = vectors.CreateLayer(
                "kept",
                srs=spatial_ref,
                geom_type=ogr.wkbPolygon,
                options=["SPATIAL_INDEX=NO"],
            )
            kept.StartTransaction()
            for feature in layer:
                geometry = feature.GetGeometryRef()
                area = geometry.GetArea() * unit * unit
                perimeter = geometry.Boundary().Length() * unit
                length = (
                    perimeter + math.sqrt(max(0, perimeter * perimeter - 16 * area))
                ) / 4
                remove = area < min_area_m2
                if road_length_m:
                    remove = remove and length < road_length_m
                if remove and preserve_border:
                    remove = not (
                        _on_border(geometry, source)
                        or _near_invalid(
                            geometry,
                            normalized,
                            bool(summary["invalid_pixels"]),
                            dilate=True,
                        )
                    )
                summary["components"] += 1
                if remove:
                    summary["removed_components"] += 1
                    continue
                new_geometry, filled = _fill_holes(
                    geometry,
                    max_hole_area_m2,
                    unit,
                    normalized,
                    bool(summary["invalid_pixels"]),
                )
                summary["filled_holes"] += filled
                item = ogr.Feature(kept.GetLayerDefn())
                item.SetGeometry(new_geometry)
                kept.CreateFeature(item)
            kept.CommitTransaction()
            kept.ResetReading()
            # Initialize only after scanning: full-scene dirty output blocks can
            # otherwise evict the input scanline tiles repeatedly in GDAL 3.4.
            result.GetRasterBand(1).Fill(0)
            result.FlushCache()
            gdal.RasterizeLayer(result, [1], kept, burn_values=[1])
            layer = kept = feature = item = vectors = None
        else:
            for y in range(0, source.RasterYSize, 512):
                h = min(512, source.RasterYSize - y)
                result.GetRasterBand(1).WriteArray(
                    normalized.GetRasterBand(1).ReadAsArray(
                        0, y, source.RasterXSize, h
                    ),
                    0,
                    y,
                )
        for y in range(0, source.RasterYSize, 512):
            h = min(512, source.RasterYSize - y)
            array = result.GetRasterBand(1).ReadAsArray(0, y, source.RasterXSize, h)
            valid = (
                normalized.GetRasterBand(2).ReadAsArray(0, y, source.RasterXSize, h) > 0
            )
            array[~valid] = 255
            summary["output_pixels"] += int((array == 1).sum())
            result.GetRasterBand(1).WriteArray(array, 0, y)
        result.FlushCache()
        result = normalized = None
    source = band = None
    partial.replace(output_path)
    summary.update(
        {
            "output": str(output_path.resolve()),
            "min_area_m2": min_area_m2,
            "max_hole_area_m2": max_hole_area_m2,
            "road_length_m": road_length_m,
            "preserve_border": preserve_border,
            "connectivity": connectivity,
        }
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-area-m2", type=float, default=0)
    parser.add_argument("--max-hole-area-m2", type=float, default=0)
    parser.add_argument("--road-length-m", type=float, default=0)
    parser.add_argument("--connectivity", type=int, choices=(4, 8), default=8)
    parser.add_argument("--no-preserve-border", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            process_mask(
                args.input,
                args.output,
                args.min_area_m2,
                args.max_hole_area_m2,
                args.road_length_m,
                not args.no_preserve_border,
                args.connectivity,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
