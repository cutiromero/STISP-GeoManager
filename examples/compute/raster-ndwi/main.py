"""McFeeters NDWI, calculated blockwise from green and NIR reflectance."""

import numpy as np
import rasterio


def run(context):
    green_band = context.parameters["green"]
    nir_band = context.parameters["nir"]
    if green_band == nir_band:
        raise ValueError("绿光与近红外波段不能相同")
    with rasterio.open(context.input_path("image")) as src:
        if not all(1 <= band <= src.count for band in (green_band, nir_band)):
            raise ValueError("所选波段超出影像范围")
        profile = src.profile.copy()
        profile.update(
            driver="GTiff", count=1, dtype="float32", nodata=-9999.0, compress="deflate"
        )
        with rasterio.open(context.output_path("ndwi.tif"), "w", **profile) as dst:
            for _, window in src.block_windows(green_band):
                green = src.read(green_band, window=window, masked=True).astype(
                    "float32"
                )
                nir = src.read(nir_band, window=window, masked=True).astype("float32")
                green = green * src.scales[green_band - 1] + src.offsets[green_band - 1]
                nir = nir * src.scales[nir_band - 1] + src.offsets[nir_band - 1]
                with np.errstate(divide="ignore", invalid="ignore"):
                    result = (green - nir) / (green + nir)
                result = np.ma.masked_where(
                    (green + nir) == 0, np.ma.masked_invalid(result)
                )
                dst.write(result.filled(-9999.0), 1, window=window)
