"""Reuse exact lithology/area grids across minerals without holding rasters in RAM."""

from contextlib import ExitStack
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely
from pyproj import CRS
from rasterio.features import rasterize

from multi_io import digest
from multi_windows import create, windows


class LithologyGrids:
    def __init__(self, directory, lithology, area):
        self.directory = Path(directory)
        self.lithology, self.area = lithology, area
        self._projection = None
        self._prepared = None
        self._grids = {}

    def prepare(self, crs):
        key = crs.to_wkt()
        if self._projection == key:
            return self._prepared
        local = self.lithology.to_crs(crs)
        area = gpd.GeoSeries([self.area], crs=self.lithology.crs).to_crs(crs).iloc[0]
        codes = sorted(set(local.geo_sym.astype(str)))
        identities = {code: index + 1 for index, code in enumerate(codes)}
        groups = {
            code: list(local.loc[local.geo_sym.astype(str) == code].geometry)
            for code in codes
        }
        # These are the same full-precision mappings rasterio obtains from each
        # geometry; prepare them once instead of once per window and mineral.
        by_code = {
            code: [(geometry.__geo_interface__, 1) for geometry in geometries]
            for code, geometries in groups.items()
        }
        entries = [
            (geometry.__geo_interface__, identities[str(code)])
            for code, geometry in zip(local.geo_sym, local.geometry)
        ]
        unions = {
            code: shapely.union_all(geometries) for code, geometries in groups.items()
        }
        self._projection = key
        self._prepared = codes, identities, entries, by_code, unions, area
        return self._prepared

    def get(self, source):
        crs = CRS.from_user_input(source.crs)
        prepared = self.prepare(crs)
        signature = digest(
            {
                "crs": crs.to_wkt(),
                "transform": list(source.transform),
                "width": source.width,
                "height": source.height,
            }
        )
        if signature in self._grids:
            return self._grids[signature], prepared
        directory = self.directory / ("grid-" + signature[:24])
        directory.mkdir()
        paths = {
            key: directory / (key + ".tif") for key in ["units", "boundary", "area"]
        }
        codes, identities, entries, by_code, unions, area = prepared
        pixel_area = abs(source.transform.determinant)
        with ExitStack() as stack:
            targets = {
                key: stack.enter_context(
                    create(path, source.profile, "int32" if key == "units" else "uint8")
                )
                for key, path in paths.items()
            }
            for window in windows(source.profile):
                shape = int(window.height), int(window.width)
                transform = source.window_transform(window)
                options = {"out_shape": shape, "transform": transform}
                units = (
                    rasterize(entries, dtype="int32", **options)
                    if entries
                    else np.zeros(shape, dtype="int32")
                )
                touched = np.zeros(shape, dtype="uint32")
                for code in codes:
                    touched += rasterize(
                        by_code[code], dtype="uint8", all_touched=True, **options
                    )
                boundary = touched > 1
                rows, columns = np.where(boundary)
                if len(rows):
                    if transform.b or transform.d:
                        raise ValueError(
                            "逐像元边界统计暂不支持旋转网格，请先转为北向网格"
                        )
                    left, top = (
                        transform.c + columns * transform.a,
                        transform.f + rows * transform.e,
                    )
                    pixels = shapely.box(
                        np.minimum(left, left + transform.a),
                        np.minimum(top, top + transform.e),
                        np.maximum(left, left + transform.a),
                        np.maximum(top, top + transform.e),
                    )
                    intersected = np.zeros(len(pixels), dtype="uint32")
                    for code in codes:
                        intersected += (
                            shapely.area(shapely.intersection(pixels, unions[code]))
                            > pixel_area * 1e-10
                        )
                    boundary[rows, columns] = intersected > 1
                mask = rasterize(
                    [(area.__geo_interface__, 1)], dtype="uint8", **options
                )
                for key, values in [
                    ("units", units),
                    ("boundary", boundary),
                    ("area", mask),
                ]:
                    targets[key].write(
                        values.astype(targets[key].dtypes[0], copy=False),
                        1,
                        window=window,
                    )
        self._grids[signature] = paths
        return paths, prepared
