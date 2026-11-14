"""Bounded, source-grid raster windows declared by published operator ports."""

from copy import deepcopy
import math

from .packages import ComputeError

MAX_WINDOW_PIXELS = 4_194_304


def windowed_metadata(spec, info, parameters):
    names = (spec.get("raster") or {}).get("window")
    if not names:
        return info
    from .preflight import gap
    from affine import Affine
    from rasterio.windows import from_bounds

    try:
        west, south, east, north = [parameters[key] for key in names]
        if any(
            type(v) not in (int, float) or not math.isfinite(v)
            for v in (west, south, east, north)
        ) or not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError()
        metadata = info["rasterMetadata"]
        if info["crs"] != "EPSG:4326":
            raise ValueError()
        transform = metadata["geoTransform"]
        if transform[2] or transform[4] or transform[1] <= 0 or transform[5] >= 0:
            raise ValueError()
        affine = Affine.from_gdal(*transform)
        region = from_bounds(west, south, east, north, affine)
        # Pixel centres determine inclusion at the requested geographic boundary.
        x = math.ceil(region.col_off - 0.5)
        y = math.ceil(region.row_off - 0.5)
        right = math.ceil(region.col_off + region.width - 0.5)
        bottom = math.ceil(region.row_off + region.height - 0.5)
        width, height = right - x, bottom - y
        if (
            x < 0
            or y < 0
            or right > metadata["size"][0]
            or bottom > metadata["size"][1]
            or min(width, height) < 1
            or width * height > MAX_WINDOW_PIXELS
        ):
            raise ValueError()
    except (KeyError, ValueError, TypeError, OverflowError) as error:
        raise ComputeError(
            "研究区须位于原始WGS84影像范围内，且不超过4194304像元",
            gaps=[
                gap(
                    "RASTER_WINDOW",
                    spec["key"],
                    "adjust_parameters",
                    expected={"crs": "EPSG:4326", "maxPixels": MAX_WINDOW_PIXELS},
                )
            ],
        ) from error
    value = deepcopy(info)
    value["rasterWindow"] = [x, y, width, height]
    value["sourceSizeBytes"] = info["sizeBytes"]
    # Budget the uncompressed window, rather than the compressed continental file.
    value["sizeBytes"] = width * height * len(metadata["bands"]) * 8 + 65536
    value["rasterMetadata"]["size"] = [width, height]
    value["rasterMetadata"]["geoTransform"] = list(
        (affine * Affine.translation(x, y)).to_gdal()
    )
    return value


def materialize_window(resource, target, window):
    import rasterio
    from rasterio.windows import Window
    from apps.core.storage import raster_source_path
    from apps.raster.models import RasterDataset

    dataset = RasterDataset.objects.get(data_resource=resource, status="ready")
    with rasterio.open(raster_source_path(dataset.source_relative_path)) as source:
        x, y, width, height = window
        region = Window(x, y, width, height)
        profile = {
            **source.profile,
            "driver": "GTiff",
            "width": width,
            "height": height,
            "transform": source.window_transform(region),
            "tiled": True,
            "blockxsize": 256,
            "blockysize": 256,
            "compress": "deflate",
        }
        with (
            rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True, GDAL_PAM_ENABLED="NO"),
            rasterio.open(target, "w", **profile) as output,
        ):
            output.update_tags(**source.tags())
            for band in range(1, source.count + 1):
                if source.descriptions[band - 1]:
                    output.set_band_description(band, source.descriptions[band - 1])
            output.scales = source.scales
            output.offsets = source.offsets
            for _, block in output.block_windows(1):
                selected = Window(
                    x + block.col_off, y + block.row_off, block.width, block.height
                )
                values = source.read(window=selected, masked=True)
                output.write(
                    values.filled(source.nodata if source.nodata is not None else 0),
                    window=block,
                )
                output.write_mask(
                    (
                        ~values.mask.any(axis=0)
                        if values.mask.ndim
                        else source.dataset_mask(window=selected) > 0
                    ).astype("uint8")
                    * 255,
                    window=block,
                )
