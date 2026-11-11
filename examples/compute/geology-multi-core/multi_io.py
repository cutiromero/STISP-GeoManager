"""Task-local IO and immutable input identities for the trial geology operators."""

import csv
import hashlib
import json
import math
from pathlib import Path
import tempfile

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import CRS
import rasterio
from rasterio.features import shapes
from shapely import set_precision
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

RASTERS = {
    "hematite": "赤铁矿化",
    "chlorite": "绿泥石化",
    "hydromica": "水云母化",
    "calcite": "方解石化",
    "dolomite": "白云石化",
}


def raster_band_identity(path):
    """Keep the exact values-then-masks digest while decoding each block once."""
    from multi_windows import ordered_windows, GDAL_CACHE_MB

    with rasterio.open(path) as src:
        if src.count != 1 or src.crs is None:
            raise ValueError("类别波段需要单波段和真实坐标系")
        pixels = hashlib.sha256()
        with (
            tempfile.SpooledTemporaryFile(max_size=8 * 1024**2) as masks,
            rasterio.Env(GDAL_CACHEMAX=GDAL_CACHE_MB * 1024**2),
        ):
            for window in ordered_windows(src):
                values = src.read(1, window=window, masked=True)
                pixels.update(values.filled(0).tobytes())
                masks.write(np.ma.getmaskarray(values).tobytes())
            masks.seek(0)
            for chunk in iter(lambda: masks.read(1024**2), b""):
                pixels.update(chunk)
        return {
            "crs": src.crs.to_wkt(),
            "transform": list(src.transform),
            "shape": src.shape,
            "pixels": pixels.hexdigest(),
        }


ISSUE_FIELDS = [
    "issue_id",
    "element",
    "feature_id",
    "rule_id",
    "rule_version",
    "knowledge_id",
    "knowledge_revision",
    "status",
    "suggested_action",
    "candidate_action",
    "candidate_target_code",
    "allowed_actions_json",
    "target_code",
    "measurements_json",
    "conditions",
    "exceptions",
    "reason",
    "snapshot_hash",
    "geometry_json",
]
CHANGE_FIELDS = [
    "issue_id",
    "feature_id",
    "rule_id",
    "rule_version",
    "snapshot_hash",
    "action",
    "target_code",
    "weight",
    "reason",
]
FORBIDDEN = {
    "inj_id",
    "inj_type",
    "fake_type",
    "truth",
    "reference_label",
    "expected_label",
}


def scalar(value):
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    return value.item() if isinstance(value, np.generic) else value


def dump(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value):
    return hashlib.sha256(dump(value).encode("utf-8")).hexdigest()


def geometry_hash(geometry):
    return hashlib.sha256(set_precision(geometry, 0.000001).normalize().wkb).hexdigest()


def table(path):
    csv.field_size_limit(20 * 1024 * 1024)
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(reader.fieldnames) != len(
            set(reader.fieldnames)
        ):
            raise ValueError("表格字段缺失或重复")
        rows = list(reader)
    if len(rows) > 100000 or any(
        None in row or any(value is None for value in row.values()) for row in rows
    ):
        raise ValueError("表格结构不完整或行数过多")
    return rows


def write_table(path, rows, fields):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def settings(context):
    result = {
        "working_epsg": context.parameters.get("working_epsg", 32646),
        "segment": context.parameters.get("segment", "all"),
        "grid_resolution_m": context.parameters.get("grid_resolution_m", 100),
        "min_zone_area_m2": context.parameters.get("min_zone_area_m2", 200000),
    }
    if type(result["working_epsg"]) is not int:
        raise ValueError("工作投影须为整数EPSG")
    crs = CRS.from_epsg(result["working_epsg"])
    if not crs.is_projected or any(
        abs(axis.unit_conversion_factor - 1) > 1e-9 for axis in crs.axis_info[:2]
    ):
        raise ValueError("计算需要米制投影")
    if result["segment"] not in {"all", "lithology", "structure", "alteration"}:
        raise ValueError("未知检查入口")
    for key, low, high in [
        ("grid_resolution_m", 10, 1000),
        ("min_zone_area_m2", 0, 100000000),
    ]:
        value = result[key]
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not low <= value <= high
        ):
            raise ValueError("网格或远景区面积参数无效")
    return result


def vector(path, epsg, geometry_types, identity=None, required=(), allow_empty=False):
    frame = gpd.read_file(path)
    if frame.crs is None or not set(required) <= set(frame) or FORBIDDEN & set(frame):
        raise ValueError("资料缺少坐标/字段，或包含评价专用标签")
    if frame.empty and not allow_empty:
        raise ValueError("输入资料为空")
    if (
        frame.geometry.isna().any()
        or frame.geometry.is_empty.any()
        or not frame.geometry.is_valid.all()
        or not set(frame.geom_type) <= set(geometry_types)
    ):
        raise ValueError("几何类型不符或存在无效几何")
    if identity and (
        identity not in frame
        or frame[identity].isna().any()
        or frame[identity].astype(str).duplicated().any()
        or frame[identity].astype(str).str.startswith("INJ").any()
    ):
        raise ValueError("需要唯一中性对象编号")
    if identity:
        frame[identity] = frame[identity].astype(str)
    return frame.to_crs(epsg).reset_index(drop=True)


def rules(path):
    rows = table(path)
    result, units, aliases = {}, None, None
    required = {
        "rule_id",
        "rule_version",
        "knowledge_id",
        "knowledge_revision",
        "params_json",
        "rule_json",
        "units_json",
        "aliases_json",
    }
    for row in rows:
        if not required <= set(row) or not all(
            row[key] for key in required - {"units_json", "aliases_json"}
        ):
            raise ValueError("场景规则须带规则版本与知识修订")
        identifier = row["rule_id"]
        if identifier in result or identifier not in {
            f"{p}-{i:02}"
            for p, count in [("L", 7), ("S", 5), ("A", 5), ("P", 3)]
            for i in range(1, count + 1)
        }:
            raise ValueError("规则编号未知或重复")
        raw, params = json.loads(row["rule_json"]), json.loads(row["params_json"])
        if (
            raw.get("id") != identifier
            or not isinstance(params, dict)
            or any(
                type(value) in (int, float) and (not math.isfinite(value) or value < 0)
                for value in params.values()
            )
        ):
            raise ValueError("规则标识或参数不一致")
        result[identifier] = {
            **raw,
            "version": row["rule_version"],
            "knowledge_id": row["knowledge_id"],
            "knowledge_revision": row["knowledge_revision"],
            "params": params,
        }
        for key in ("units_json", "aliases_json"):
            if row[key]:
                value = json.loads(row[key])
                if not isinstance(value, dict):
                    raise ValueError("填图单元及别名须为对象")
                old = units if key == "units_json" else aliases
                if old is not None and old != value:
                    raise ValueError("填图单元或别名表版本冲突")
                if key == "units_json":
                    units = value
                else:
                    aliases = value
    if (
        not result
        or not units
        or not aliases
        or not set(aliases.values()) <= set(units)
    ):
        raise ValueError("缺少已冻结的规则、填图单元或名称代号映射")
    return result, units, aliases


def frame_identity(frame):
    records = [
        {
            **{
                key: scalar(row[key])
                for key in sorted(set(frame) - {frame.geometry.name})
            },
            "geometry": geometry_hash(row.geometry),
        }
        for _, row in frame.iterrows()
    ]
    return sorted(records, key=dump)


def inputs(context, config, include_rasters=True):

    epsg = config["working_epsg"]
    lithology = vector(
        context.input_path("lithology"),
        epsg,
        {"Polygon", "MultiPolygon"},
        "feature_id",
        {"name", "geo_sym"},
    )
    faults = vector(
        context.input_path("faults"),
        epsg,
        {"LineString", "MultiLineString"},
        "line_id",
        allow_empty=True,
    )
    coverage = vector(context.input_path("coverage"), epsg, {"Polygon", "MultiPolygon"})
    area = unary_union(coverage.geometry)
    if "role" in coverage:
        area = unary_union(
            coverage.loc[coverage.role != "exclusion", "geometry"]
        ).difference(
            unary_union(coverage.loc[coverage.role == "exclusion", "geometry"])
        )
    if area.is_empty:
        raise ValueError("制图范围没有可计算区域")
    if not area.buffer(0.01).covers(unary_union(lithology.geometry)):
        raise ValueError("岩性图超出制图范围，请裁剪到研究区")
    if len(faults) and not area.buffer(0.01).covers(unary_union(faults.geometry)):
        raise ValueError("构造资料超出研究区，请使用研究区内中性编号副本")
    knowledge, units, aliases = rules(context.input_path("rules"))
    raster_identity = {}
    if include_rasters:
        for key in RASTERS:
            verified = (
                context.input_evidence(key)
                if hasattr(context, "input_evidence")
                else None
            )
            if verified and verified.get("raster") is not None:
                raster_identity[key] = verified["raster"]
            else:
                raster_identity[key] = raster_band_identity(context.input_path(key))
            try:
                weight_path = context.input_path(key + "_weight")
            except KeyError:
                weight_path = None
            if weight_path:
                verified_weight = (
                    context.input_evidence(key + "_weight")
                    if hasattr(context, "input_evidence")
                    else None
                )
                if verified_weight:
                    raster_identity[key + "_weight"] = verified_weight["sha256"]
                else:
                    with Path(weight_path).open("rb") as stream:
                        raster_identity[key + "_weight"] = hashlib.file_digest(
                            stream, "sha256"
                        ).hexdigest()
    payload = {
        **(
            {"class_labels": context._class_mask_labels}
            if hasattr(context, "_class_mask_labels")
            else {}
        ),
        "lithology": frame_identity(lithology),
        "faults": frame_identity(faults),
        "coverage": frame_identity(coverage),
        "rules": knowledge,
        "units": units,
        "aliases": aliases,
        "rasters": raster_identity,
        "parameters": config,
    }
    return lithology, faults, area, knowledge, units, aliases, digest(payload)


def alterations(context, config, area):
    frames = []
    for key, label in RASTERS.items():
        with rasterio.open(context.input_path(key)) as src:
            values = src.read(1, masked=True)
            mask = (~np.ma.getmaskarray(values)) & (values.filled(0) == 1)
            geometries = [
                shape(geometry)
                for geometry, _ in shapes(
                    mask.astype("uint8"), mask=mask, transform=src.transform
                )
            ]
            part = gpd.GeoDataFrame(
                {"alt": [label] * len(geometries)}, geometry=geometries, crs=src.crs
            ).to_crs(config["working_epsg"])
        if len(part):
            part.geometry = part.geometry.intersection(area)
            part = part.loc[~part.geometry.is_empty & (part.geometry.area > 0)].copy()
            part["feature_id"] = [
                "M-" + digest([key, geometry_hash(geometry)])[:20]
                for geometry in part.geometry
            ]
            frames.append(part)
    if not frames:
        return gpd.GeoDataFrame(
            columns=["alt", "feature_id", "state", "weight", "geometry"],
            geometry="geometry",
            crs=config["working_epsg"],
        )
    result = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True), crs=config["working_epsg"]
    )
    result["state"], result["weight"] = "keep", 1.0
    return result


def load_alterations(context, config, area, snapshot):
    fresh = alterations(context, config, area)
    try:
        path = context.input_path("alterations")
    except KeyError:
        path = None
    if path:
        prior = vector(
            path,
            config["working_epsg"],
            {"Polygon", "MultiPolygon"},
            "feature_id",
            {"alt", "state", "weight"},
            allow_empty=True,
        )
        if set(prior.feature_id) != set(fresh.feature_id):
            raise ValueError("蚀变状态图层与原识别影像的对象范围不一致")
        indexed = prior.set_index("feature_id")
        for index, row in fresh.iterrows():
            old = indexed.loc[row.feature_id]
            if (
                old.alt != row.alt
                or not old.geometry.equals_exact(row.geometry, 0.00001)
                or old.state not in {"keep", "review", "downweight", "exclude"}
            ):
                raise ValueError("蚀变对象几何、类别或处理状态被改变")
            weight = float(old.weight)
            if (
                not math.isfinite(weight)
                or not 0 <= weight <= 1
                or old.state == "exclude"
                and weight != 0
                or old.state == "downweight"
                and not 0 < weight < 1
                or old.state in {"keep", "review"}
                and weight != 1
            ):
                raise ValueError("蚀变状态与权重不一致")
            fresh.at[index, "state"], fresh.at[index, "weight"] = old.state, weight
    return fresh, digest({"inputs": snapshot, "alterations": frame_identity(fresh)})


def write_vector(path, frame, epsg, geometry_type="Unknown"):
    # Empty results remain explicit in CSV/quality; platform vector import needs >=1.
    frame = frame.copy()
    if frame.empty:
        return
    else:
        frame.to_crs(epsg).to_file(path, layer="data", driver="GPKG", index=False)


def report(context, metrics, summary):
    value = {
        "version": 1,
        "status": "passed",
        "summary": summary,
        "metrics": metrics,
        "knowledgeFacts": {"geologyMulti": metrics},
    }
    Path(context.output_path("quality.json")).write_text(dump(value), encoding="utf-8")


def geojson_geometry(geometry, epsg):
    # Display geometry travels with approvals. Canonical decimal coordinates
    # avoid CPU/PROJ last-bit differences; input identities and measurements
    # retain their original precision and are still compared exactly.
    def rounded(value):
        if isinstance(value, dict):
            return {key: rounded(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [rounded(item) for item in value]
        return round(value, 9) if isinstance(value, float) else value

    return dump(
        rounded(mapping(gpd.GeoSeries([geometry], crs=epsg).to_crs(4326).iloc[0]))
    )
