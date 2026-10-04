"""Repair planar polygon topology, with source retention and per-row evidence."""

import csv
import hashlib
import json
import math
from pathlib import Path
import tempfile
import zipfile

import geopandas as gpd
from pyproj import CRS, Geod, Transformer
from shapely import make_valid
from shapely.errors import GEOSException
from shapely.geometry import MultiPolygon
from shapely.ops import orient, transform
from shapely.validation import explain_validity

FIELDS = {"repair_row", "repair_status", "repair_review"}


def _parts(geometry):
    if geometry is None or geometry.is_empty:
        return [], []
    if geometry.geom_type == "Polygon":
        return [geometry], []
    if geometry.geom_type in {"MultiPolygon", "GeometryCollection"}:
        polygons, other = [], []
        for part in geometry.geoms:
            faces, fragments = _parts(part)
            polygons.extend(faces)
            other.extend(fragments)
        return polygons, other
    return [], [geometry]


def _area_function(crs):
    crs = CRS.from_user_input(crs)
    if crs.is_projected and len(crs.axis_info) >= 2:
        factor = math.prod(axis.unit_conversion_factor for axis in crs.axis_info[:2])
        if not math.isfinite(factor) or factor <= 0:
            raise ValueError("投影坐标系缺少有效的长度单位")
        return lambda geometry: abs(geometry.area) * factor, "projected_m2"
    if not crs.is_geographic:
        raise ValueError("输入需要地理或投影坐标系")
    transformer = Transformer.from_crs(crs, 4326, always_xy=True)
    geod = Geod(ellps="WGS84")

    def area(geometry):
        geographic = transform(transformer.transform, geometry)
        west, south, east, north = geographic.bounds
        if east - west > 180 or south < -90 or north > 90:
            return math.nan
        polygons, _ = _parts(geographic)
        return sum(
            abs(geod.geometry_area_perimeter(orient(face, sign=1.0))[0])
            for face in polygons
        )

    return area, "wgs84_ellipsoidal_m2"


def _finite_area(geometry, area):
    if geometry is None or geometry.is_empty:
        return None
    value = area(geometry)
    return value if math.isfinite(value) else None


def _repair_row(geometry, row_number, area, threshold):
    before_valid = bool(
        geometry is not None and not geometry.is_empty and geometry.is_valid
    )
    candidate = geometry
    reasons = []
    if geometry is None or geometry.is_empty:
        reasons.append("输入几何为空")
    elif not before_valid:
        try:
            candidate = make_valid(geometry)
        except GEOSException:
            reasons.append("几何修复失败，原始几何已保留")
    faces, fragments = _parts(candidate)
    polygon = faces[0] if len(faces) == 1 else MultiPolygon(faces) if faces else None
    after_valid = bool(
        polygon is not None and not polygon.is_empty and polygon.is_valid
    )
    if not after_valid:
        reasons.append("未得到有效非空面")
    if fragments:
        reasons.append("包含降维片段，完整候选已保留在审核包")
    before_faces, _ = _parts(geometry)
    if len(before_faces) != len(faces):
        reasons.append("面分量数量改变")
    before_area = _finite_area(geometry, area)
    after_area = _finite_area(polygon, area) if after_valid else None
    change_pct = None
    if before_area is None or after_area is None:
        reasons.append("面积无法比较")
    elif before_area <= 1e-12:
        reasons.append("原面积为零，需审核修复边界")
    else:
        change_pct = 100 * abs(after_area - before_area) / before_area
        if change_pct > threshold:
            reasons.append("面积变化超过阈值")
    status = "unchanged" if before_valid else "repaired" if after_valid else "failed"
    record = {
        "repair_row": row_number,
        "status": status,
        "valid_before": before_valid,
        "valid_after": after_valid,
        "reason_before": explain_validity(geometry)
        if geometry is not None
        else "Missing geometry",
        "type_before": geometry.geom_type if geometry is not None else "None",
        "type_after": polygon.geom_type if after_valid else "None",
        "candidate_type": candidate.geom_type if candidate is not None else "None",
        "parts_before": len(before_faces),
        "parts_after": len(faces),
        "non_polygon_parts": len(fragments),
        "area_before_m2": before_area,
        "area_before_trustworthy": before_valid,
        "area_after_m2": after_area,
        "area_change_pct": change_pct,
        "needs_review": bool(reasons),
        "review_reasons": "；".join(reasons),
    }
    return candidate, polygon, record


def _write_csv(path, records):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def run(context):
    source = Path(context.input_path("features"))
    with source.open("rb") as stream:
        source_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    frame = gpd.read_file(source, layer="data")
    if frame.crs is None:
        raise ValueError("输入矢量需要已知坐标系")
    if frame.empty:
        raise ValueError("输入面图层为空")
    if FIELDS & {str(column).casefold() for column in frame.columns}:
        raise ValueError(
            "输入已有修复记录字段，请重命名 repair_row/repair_status/repair_review"
        )
    if any(
        geometry is not None and geometry.geom_type not in {"Polygon", "MultiPolygon"}
        for geometry in frame.geometry
    ):
        raise ValueError("修复算子仅接受面或多面要素")
    threshold = context.parameters.get("max_area_change_pct", 5)
    if (
        type(threshold) not in {int, float}
        or not math.isfinite(threshold)
        or not 0 <= threshold <= 100
    ):
        raise ValueError("面积变化阈值须为0至100之间的有限数字")
    area, area_basis = _area_function(frame.crs)
    candidates, polygons, records = [], [], []
    for row_number, geometry in enumerate(frame.geometry, start=1):
        candidate, polygon, record = _repair_row(geometry, row_number, area, threshold)
        candidates.append(candidate)
        polygons.append(polygon)
        records.append(record)
    result = frame.copy()
    result["repair_row"] = [record["repair_row"] for record in records]
    result["repair_status"] = [record["status"] for record in records]
    result["repair_review"] = [record["needs_review"] for record in records]
    complete = all(record["valid_after"] for record in records)
    if complete:
        result.geometry = polygons
        result.to_file(
            context.output_path("repaired.gpkg"),
            layer="repaired",
            driver="GPKG",
            index=False,
        )
    summary = {
        "algorithm": "vector-geometry-repair",
        "version": "1.0.0",
        "total_features": len(records),
        "valid_before": sum(record["valid_before"] for record in records),
        "valid_after": sum(record["valid_after"] for record in records),
        "repaired": sum(record["status"] == "repaired" for record in records),
        "failed": sum(record["status"] == "failed" for record in records),
        "needs_review": sum(record["needs_review"] for record in records),
        "complete_vector": complete,
        "area_basis": area_basis,
        "max_area_change_pct": threshold,
        "source_sha256": source_digest,
        "source_crs": str(frame.crs),
    }
    log_path = context.output_path("repair-log.csv")
    summary_path = context.output_path("repair-summary.csv")
    _write_csv(log_path, records)
    _write_csv(summary_path, [summary])
    quality = {
        "version": 1,
        "status": "passed"
        if complete and summary["needs_review"] == 0
        else "needs_review",
        "summary": f"检查{len(records)}个面要素，修复后有效{summary['valid_after']}个，需审核{summary['needs_review']}个。",
        "metrics": {
            "totalFeatures": len(records),
            "validAfter": summary["valid_after"],
            "needsReview": summary["needs_review"],
            "failed": summary["failed"],
            "maxAreaChangePct": threshold,
        },
        "knowledgeFacts": {
            "geometryRepair": {
                "totalFeatures": len(records),
                "validAfter": summary["valid_after"],
                "needsReview": summary["needs_review"],
                "sourceSha256": source_digest,
            }
        },
    }
    quality_path = context.output_path("quality.json")
    quality_path.write_text(
        json.dumps(quality, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    archive_path = context.output_path("repair-audit.zip")
    with tempfile.TemporaryDirectory(dir=archive_path.parent) as temp:
        candidate_path = Path(temp) / "repair-candidates.gpkg"
        result.geometry = candidates
        result.to_file(candidate_path, layer="candidates", driver="GPKG", index=False)
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(source, "original-input.gpkg")
            for path in (candidate_path, log_path, summary_path, quality_path):
                archive.write(path, path.name)
