from __future__ import annotations

import math
from typing import Any

from apps.catalog.importer import position_error_meters


UNCERTAINTY_RATIO_THRESHOLD = 200


class GeometryValidationAccumulator:
    """Validate geometry chunks without retaining every coordinate in memory."""

    def __init__(self) -> None:
        self.missing_geometry_count = 0
        self.invalid_longitude_count = 0
        self.invalid_latitude_count = 0
        self.minimum_error: float | None = None
        self.maximum_error: float | None = None

    def filter(self, gdf):
        keep_indexes = []

        for index, geometry in gdf.geometry.items():
            has_coordinates = False
            has_invalid_longitude = False
            has_invalid_latitude = False
            geometry_minimum_error: float | None = None
            geometry_maximum_error: float | None = None

            for longitude, latitude in _coordinate_pairs(geometry):
                has_coordinates = True
                longitude_is_valid = _is_finite(longitude) and -180 <= longitude <= 180
                latitude_is_valid = _is_finite(latitude) and -90 <= latitude <= 90
                has_invalid_longitude = has_invalid_longitude or not longitude_is_valid
                has_invalid_latitude = has_invalid_latitude or not latitude_is_valid
                if not longitude_is_valid or not latitude_is_valid:
                    continue

                error = position_error_meters(str(longitude), str(latitude))
                if error <= 0:
                    continue
                geometry_minimum_error = (
                    error
                    if geometry_minimum_error is None
                    else min(geometry_minimum_error, error)
                )
                geometry_maximum_error = (
                    error
                    if geometry_maximum_error is None
                    else max(geometry_maximum_error, error)
                )

            if not has_coordinates:
                self.missing_geometry_count += 1
                continue
            if has_invalid_longitude:
                self.invalid_longitude_count += 1
            if has_invalid_latitude:
                self.invalid_latitude_count += 1
            if has_invalid_longitude or has_invalid_latitude:
                continue

            keep_indexes.append(index)
            if geometry_minimum_error is not None:
                self.minimum_error = (
                    geometry_minimum_error
                    if self.minimum_error is None
                    else min(self.minimum_error, geometry_minimum_error)
                )
            if geometry_maximum_error is not None:
                self.maximum_error = (
                    geometry_maximum_error
                    if self.maximum_error is None
                    else max(self.maximum_error, geometry_maximum_error)
                )

        return gdf.loc[keep_indexes]

    def warnings(self) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []

        if self.missing_geometry_count:
            warnings.append(
                {
                    "code": "missing_geometry",
                    "count": self.missing_geometry_count,
                    "message": f"已忽略 {self.missing_geometry_count} 条不含地理坐标的数据。",
                }
            )
        if self.invalid_longitude_count:
            warnings.append(
                {
                    "code": "invalid_longitude",
                    "count": self.invalid_longitude_count,
                    "message": f"已忽略 {self.invalid_longitude_count} 条经度不在 -180 到 180 范围内的数据。",
                }
            )
        if self.invalid_latitude_count:
            warnings.append(
                {
                    "code": "invalid_latitude",
                    "count": self.invalid_latitude_count,
                    "message": f"已忽略 {self.invalid_latitude_count} 条纬度不在 -90 到 90 范围内的数据。",
                }
            )

        _append_uncertainty_warning(warnings, self.minimum_error, self.maximum_error)
        return warnings


def validate_geojson_geometries(gdf) -> tuple[Any, list[dict[str, Any]]]:
    accumulator = GeometryValidationAccumulator()
    filtered = accumulator.filter(gdf)
    return filtered, accumulator.warnings()


def _append_uncertainty_warning(
    warnings: list[dict[str, Any]],
    minimum: float | None,
    maximum: float | None,
) -> None:
    if minimum is None or maximum is None or minimum <= 0:
        return
    ratio = maximum / minimum
    if ratio <= UNCERTAINTY_RATIO_THRESHOLD:
        return
    warnings.append(
        {
            "code": "coordinate_uncertainty",
            "minMeters": round(minimum, 6),
            "maxMeters": round(maximum, 6),
            "ratio": round(ratio, 2),
            "message": (
                f"坐标不确定性差距超过 {UNCERTAINTY_RATIO_THRESHOLD} 倍："
                f"最小约 {minimum:.6f} 米，最大约 {maximum:.6f} 米。"
            ),
        }
    )


def _coordinate_pairs(geometry):
    if geometry is None or getattr(geometry, "is_empty", True):
        return

    geometry_type = getattr(geometry, "geom_type", "")
    if geometry_type == "Point":
        longitude, latitude = geometry.x, geometry.y
        yield float(longitude), float(latitude)
        return
    if geometry_type in {"LineString", "LinearRing"}:
        for coordinate in geometry.coords:
            yield float(coordinate[0]), float(coordinate[1])
        return
    if geometry_type == "Polygon":
        for coordinate in geometry.exterior.coords:
            yield float(coordinate[0]), float(coordinate[1])
        for interior in geometry.interiors:
            for coordinate in interior.coords:
                yield float(coordinate[0]), float(coordinate[1])
        return
    if hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from _coordinate_pairs(part)


def _is_finite(value: float) -> bool:
    return math.isfinite(value)
