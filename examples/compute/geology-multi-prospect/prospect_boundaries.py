"""Extract connected regions directly from a smooth, continuous evidence field."""

import contourpy
import numpy as np
from scipy.ndimage import zoom
from shapely import make_valid
from shapely.geometry import Polygon
from shapely.ops import unary_union


def polygon_parts(geometry):
    geometry = make_valid(geometry)
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type in {"MultiPolygon", "GeometryCollection"}:
        return [part for group in geometry.geoms for part in polygon_parts(group)]
    return []


def merge_connected(geometries):
    parts = polygon_parts(unary_union(geometries))
    groups = []
    pending = set(range(len(parts)))
    while pending:
        start = min(pending)
        pending.remove(start)
        component, queue = [parts[start]], [start]
        while queue:
            current = queue.pop()
            neighbours = sorted(
                index for index in pending if parts[current].intersects(parts[index])
            )
            for index in neighbours:
                pending.remove(index)
                component.append(parts[index])
                queue.append(index)
        groups.append(unary_union(component))
    return groups


def extract_regions(margin, transform, allowed):
    """One connected superlevel set is one region, irrespective of peak count.

    Interpolate the field at half-cell spacing before extracting its zero contour.
    Boundaries are not buffered, divided between peaks or separated by fake gaps.
    """
    if not np.isfinite(margin).all():
        raise ValueError("连续支持场包含非有限值")
    if not (margin > 0).any():
        return []
    positive_rows, positive_columns = np.nonzero(margin > 0)
    row_start = max(0, int(positive_rows.min()) - 1)
    row_stop = min(margin.shape[0], int(positive_rows.max()) + 2)
    col_start = max(0, int(positive_columns.min()) - 1)
    col_stop = min(margin.shape[1], int(positive_columns.max()) + 2)
    padded = np.pad(
        margin[row_start:row_stop, col_start:col_stop], 1, constant_values=-1
    )
    # Half-cell sampling approximates a smooth level curve without changing the
    # 50 m evidence resolution; linear interpolation cannot create new extrema.
    rows = np.arange(0, padded.shape[0] - 0.5, 0.5)
    columns = np.arange(0, padded.shape[1] - 0.5, 0.5)
    values = zoom(
        padded,
        zoom=(
            (2 * padded.shape[0] - 1) / padded.shape[0],
            (2 * padded.shape[1] - 1) / padded.shape[1],
        ),
        order=1,
        prefilter=False,
        mode="nearest",
    )
    generator = contourpy.contour_generator(
        x=transform.c + (col_start + columns - 0.5) * transform.a,
        y=transform.f + (row_start + rows - 0.5) * transform.e,
        z=values,
        fill_type="OuterOffset",
        corner_mask=False,
    )
    points, offsets = generator.filled(0, float(values.max()) + 1)
    polygons = []
    for coordinates, rings in zip(points, offsets):
        paths = [coordinates[start:end] for start, end in zip(rings[:-1], rings[1:])]
        polygons.extend(polygon_parts(Polygon(paths[0], paths[1:])))
    # Union before assigning IDs, so intersecting or connected footprints cannot
    # survive as different regions. Clipping enforces actual source coverage.
    merged = unary_union(polygons).intersection(allowed)
    return merge_connected([merged])


def topology_report(geometries):
    overlaps, distances = [], []
    for index, first in enumerate(geometries):
        if not first.is_valid:
            raise ValueError("圈区边界无效")
        for second in geometries[index + 1 :]:
            overlaps.append(float(first.intersection(second).area))
            distances.append(float(first.distance(second)))
            if first.intersects(second):
                raise ValueError("相连或重叠范围必须合并为同一区")
    return {
        "boundary_method": "continuous_support_zero_contour",
        "maximum_overlap_m2": max(overlaps, default=0),
        "actual_minimum_distance_m": min(distances, default=None),
        "pair_count": len(overlaps),
        "artificial_partition": False,
        "artificial_gap_m": 0,
    }
