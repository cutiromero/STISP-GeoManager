"""Pixel-preserving alteration inspection with bounded disk-backed workspaces."""

import gc
import json
import math
import shutil
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import CRS
from rasterio.features import rasterize
from rasterio.shutil import copy as raster_copy
from rasterio.warp import Resampling, reproject
from shapely.geometry import box

from multi_io import RASTERS, digest, dump, geojson_geometry, write_table
from multi_windows import Components, GDAL_CACHE_MB, create, windows
from multi_grid import LithologyGrids

RULE_PRIORITY = ("A-04", "A-01", "A-02", "A-03", "A-05")
SUMMARY_FIELDS = [
    "group_id",
    "rule_id",
    "rule_version",
    "knowledge_id",
    "knowledge_revision",
    "mineral",
    "unit_code",
    "rock_group",
    "boundary",
    "suggested_action",
    "status",
    "pixel_count",
    "area_m2",
    "component_count",
    "bbox_json",
    "representatives_json",
]
QUALITY_FIELDS = [
    "mineral",
    "original_pixels",
    "hit_pixels",
    "retained_pixels",
    "original_area_m2",
    "hit_area_m2",
    "retained_area_m2",
    "hydrothermal_pixels",
    "hydrothermal_area_m2",
    "boundary_pixels",
]


def empty_vectors(epsg):
    return gpd.GeoDataFrame(
        columns=["alt", "feature_id", "state", "weight", "geometry"],
        geometry="geometry",
        crs=epsg,
    )


def burn(entries, profile, **options):
    if not entries:
        return np.zeros((profile["height"], profile["width"]), dtype="int32")
    return rasterize(
        entries,
        out_shape=(profile["height"], profile["width"]),
        transform=profile["transform"],
        **options,
    )


def pixel_bounds(row0, col0, row1, col1, profile):
    transform = profile["transform"]
    corners = [
        transform * (column, row) for column in (col0, col1) for row in (row0, row1)
    ]
    return [
        min(point[0] for point in corners),
        min(point[1] for point in corners),
        max(point[0] for point in corners),
        max(point[1] for point in corners),
    ]


def window_profile(source, window):
    return {
        **source.profile,
        "height": int(window.height),
        "width": int(window.width),
        "transform": source.window_transform(window),
    }


def read_raw(source, window, area, mask=None):
    values = source.read(1, window=window, masked=True)
    valid = ~np.ma.getmaskarray(values)
    if not np.isin(values.data[valid], [0, 1]).all():
        raise ValueError("蚀变输入必须为0/1栅格")
    raw = valid & (values.data == 1)
    raw &= (
        burn([(area, 1)], window_profile(source, window), dtype="uint8")
        if mask is None
        else mask
    ) > 0
    return raw


def read_weights(source, window, shape):
    weights = (
        source.read(1, window=window) if source else np.ones(shape, dtype="float32")
    )
    if not np.isfinite(weights).all() or ((weights < 0) | (weights > 1)).any():
        raise ValueError("蚀变权重必须在0和1之间")
    return weights


def open_weights(context, mineral, source, stack):
    try:
        path = context.input_path(mineral + "_weight")
    except KeyError:
        return None
    weights = stack.enter_context(rasterio.open(path))
    if (
        weights.crs != source.crs
        or weights.transform != source.transform
        or weights.shape != source.shape
    ):
        raise ValueError("蚀变权重与识别网格不一致")
    return weights


def publish(context, mineral, suffix, source, description):
    source.set_band_description(1, description)
    source.update_tags(protocol="alteration-pixels-v1")
    source.close()
    raster_copy(
        source.name,
        context.output_path(f"{mineral}_{suffix}.tif"),
        driver="COG",
        compress="DEFLATE",
        blocksize=256,
    )


class RasterAlterations:
    def __init__(self, context, config, area):
        self.context, self.config, self.area = context, config, area
        self.minerals, self.groups, self.summaries, self.quality = {}, {}, [], []
        self.snapshot = ""
        self.alt = np.array(list(RASTERS.values()))
        self.workspace = None

    def __len__(self):
        return len(self.summaries)

    def inspect(self, lithology, rules, units, snapshot):
        self.snapshot = snapshot
        self.inspection = lithology, rules, units
        self.workspace = TemporaryDirectory(
            prefix=".raster-",
            dir=Path(self.context.output_path("alteration_summary.csv")).parent,
        )
        self.grids = LithologyGrids(self.workspace.name, lithology, self.area)
        findings = []
        with rasterio.Env(GDAL_CACHEMAX=GDAL_CACHE_MB * 1024 * 1024):
            for mineral, name in RASTERS.items():
                findings.extend(
                    self._inspect_mineral(mineral, name, lithology, rules, units)
                )
                gc.collect()
        return findings, self

    def _inspect_mineral(self, mineral, name, lithology, rules, units):
        directory = Path(self.workspace.name) / mineral
        directory.mkdir()
        with ExitStack() as stack:
            source = stack.enter_context(
                rasterio.open(self.context.input_path(mineral))
            )
            profile = source.profile.copy()
            crs = CRS.from_user_input(source.crs)
            if not crs.is_projected or any(
                abs(axis.unit_conversion_factor - 1) > 1e-9
                for axis in crs.axis_info[:2]
            ):
                raise ValueError("蚀变逐像元面积判断需要米制投影栅格，请先重投影输入")
            pixel_area = abs(source.transform.determinant)
            if not math.isfinite(pixel_area) or pixel_area <= 0:
                raise ValueError("蚀变网格像元面积无效")
            grid_paths, prepared = self.grids.get(source)
            codes, identities, _, _, _, area = prepared
            grids = {
                key: stack.enter_context(rasterio.open(path))
                for key, path in grid_paths.items()
            }
            weights = open_weights(self.context, mineral, source, stack)
            layers = {
                key: stack.enter_context(
                    create(directory / (key + ".tif"), profile, dtype)
                )
                for key, dtype in {
                    "raw": "uint8",
                    "weights": weights.dtypes[0] if weights else "float32",
                    "units": "int32",
                    "boundary": "uint8",
                    "hits": "uint8",
                    "groups": "uint32",
                }.items()
            }
            original, boundary_count, positive = 0, 0, 0
            selected_counts = {}
            for window in windows(profile):
                raw = read_raw(
                    source, window, area, grids["area"].read(1, window=window)
                )
                unit_grid = grids["units"].read(1, window=window)
                boundary = grids["boundary"].read(1, window=window) > 0
                original += int(raw.sum())
                unit_ids, unit_counts = np.unique(unit_grid[raw], return_counts=True)
                for identity, count in zip(unit_ids.tolist(), unit_counts.tolist()):
                    selected_counts[identity] = selected_counts.get(identity, 0) + count
                boundary_count += int((raw & boundary).sum())
                if mineral in {"calcite", "dolomite"}:
                    for code in codes:
                        if code and units.get(code, {}).get("group", "unknown") not in {
                            "carbonate",
                            "carbonate_interbed",
                            "loose",
                            "unknown",
                            "",
                        }:
                            positive += int(
                                (raw & (unit_grid == identities[code])).sum()
                            )
                for key, values in {
                    "raw": raw,
                    "weights": read_weights(weights, window, raw.shape),
                    "units": unit_grid,
                    "boundary": boundary,
                }.items():
                    layers[key].write(
                        values.astype(layers[key].dtypes[0], copy=False),
                        1,
                        window=window,
                    )
                for key in ("hits", "groups"):
                    layers[key].write(
                        np.zeros(raw.shape, dtype=layers[key].dtypes[0]),
                        1,
                        window=window,
                    )
            findings = []
            for code in codes + [""]:
                index = identities.get(code, 0)
                if not selected_counts.get(index):
                    continue
                group = units.get(code, {}).get("group", "unknown")

                def selected(window):
                    return (layers["raw"].read(1, window=window) > 0) & (
                        layers["units"].read(1, window=window) == index
                    )

                with ExitStack() as components:
                    small = (
                        components.enter_context(
                            Components(directory / "small.tif", source, selected)
                        )
                        if "A-05" in rules
                        else None
                    )
                    for rule_id in RULE_PRIORITY:
                        if rule_id not in rules or self.config["segment"] not in {
                            "all",
                            "alteration",
                        }:
                            continue
                        action, matches = {
                            "A-01": (
                                "exclude",
                                group == "carbonate"
                                and mineral in {"calcite", "dolomite"},
                            ),
                            "A-02": (
                                "review",
                                group == "carbonate_interbed"
                                and mineral in {"calcite", "dolomite"},
                            ),
                            "A-03": (
                                "downweight",
                                group == "red_clastic" and mineral == "hematite",
                            ),
                            "A-04": ("exclude", group == "loose"),
                            "A-05": ("downweight", True),
                        }[rule_id]
                        if not matches:
                            continue
                        for mixed in (False, True):
                            if mixed and not boundary_count:
                                continue

                            def candidate(window):
                                cells = selected(window) & (
                                    layers["hits"].read(1, window=window) == 0
                                )
                                if rule_id == "A-05":
                                    cells &= small.small(
                                        window,
                                        rules[rule_id]["params"].get(
                                            "min_area_m2", 2600
                                        )
                                        / pixel_area,
                                    )
                                return cells & (
                                    layers["boundary"].read(1, window=window) == mixed
                                )

                            with Components(
                                directory / "candidate.tif", source, candidate
                            ) as connected:
                                count, pixels, bounds, top = connected.summary()
                                if not pixels:
                                    continue
                                bounds = pixel_bounds(*bounds, profile)
                                representatives = [
                                    {
                                        "bbox": pixel_bounds(*row[1:], profile),
                                        "area_m2": row[0] * pixel_area,
                                    }
                                    for row in top
                                ]
                                finding, ordinal = self._finding(
                                    mineral,
                                    name,
                                    code,
                                    group,
                                    mixed,
                                    action,
                                    rule_id,
                                    rules[rule_id],
                                    pixels,
                                    count,
                                    bounds,
                                    representatives,
                                    pixel_area,
                                    crs,
                                )
                                findings.append(finding)
                                for window in windows(profile):
                                    cells = connected.labels.read(1, window=window) > 0
                                    for key, value in (
                                        ("hits", int(rule_id[-2:])),
                                        ("groups", ordinal),
                                    ):
                                        values = layers[key].read(1, window=window)
                                        values[cells] = value
                                        layers[key].write(values, 1, window=window)
            hit = sum(
                int(np.count_nonzero(layers["hits"].read(1, window=window)))
                for window in windows(profile)
            )
            self.minerals[mineral] = {
                key: Path(layer.name) for key, layer in layers.items()
            }
            self.quality.append(
                dict(
                    zip(
                        QUALITY_FIELDS,
                        [
                            mineral,
                            original,
                            hit,
                            original,
                            original * pixel_area,
                            hit * pixel_area,
                            original * pixel_area,
                            positive,
                            positive * pixel_area,
                            boundary_count,
                        ],
                    )
                )
            )
        return findings

    def _finding(
        self,
        mineral,
        name,
        code,
        group,
        mixed,
        action,
        rule_id,
        rule,
        count,
        components,
        bounds,
        representatives,
        pixel_area,
        crs,
    ):
        group_id = (
            "AG-"
            + digest(
                ["alteration-pixels-v1", rule_id, mineral, code, group, mixed, action]
            )[:24]
        )
        if group_id in self.groups:
            _, ordinal, finding = self.groups[group_id]
            return finding, ordinal
        summary = dict(
            zip(
                SUMMARY_FIELDS,
                [
                    group_id,
                    rule_id,
                    rule["version"],
                    rule["knowledge_id"],
                    rule["knowledge_revision"],
                    mineral,
                    code,
                    group,
                    mixed,
                    action,
                    "review" if action == "review" else "suggested",
                    count,
                    count * pixel_area,
                    components,
                    dump(bounds),
                    dump(representatives),
                ],
            )
        )
        self.summaries.append(summary)
        measurements = {
            key: summary[key]
            for key in (
                "group_id",
                "mineral",
                "unit_code",
                "rock_group",
                "boundary",
                "pixel_count",
                "area_m2",
                "component_count",
            )
        }
        measurements.update(
            bbox=bounds,
            representatives=representatives,
            raster_protocol="alteration-pixels-v1",
        )
        geometry = (
            gpd.GeoSeries([box(*bounds)], crs=crs)
            .to_crs(self.config["working_epsg"])
            .iloc[0]
        )
        finding = {
            "issue_id": group_id,
            "element": "alteration",
            "feature_id": group_id,
            "rule_id": rule_id,
            "rule_version": rule["version"],
            "knowledge_id": rule["knowledge_id"],
            "knowledge_revision": rule["knowledge_revision"],
            "status": summary["status"],
            "suggested_action": action,
            "candidate_action": "exclude" if action == "review" else "",
            "candidate_target_code": "",
            "allowed_actions_json": dump(["keep", "review", "downweight", "exclude"]),
            "target_code": "",
            "measurements_json": dump(measurements),
            "conditions": "",
            "exceptions": "",
            "reason": rule_id
            + " · "
            + name
            + " · "
            + (code or "未覆盖")
            + (" · 边界像元" if mixed else ""),
            "snapshot_hash": self.snapshot,
            "geometry_json": geojson_geometry(geometry, self.config["working_epsg"]),
            "_geometry": geometry,
        }
        ordinal = len(self.groups) + 1
        self.groups[group_id] = (mineral, ordinal, finding)
        return finding, ordinal

    def outputs(self, context, operations=None):
        actual = []
        selected = {row["feature_id"]: row for row in operations or []}
        with rasterio.Env(GDAL_CACHEMAX=GDAL_CACHE_MB * 1024 * 1024):
            for mineral in self.minerals:
                paths = self.minerals[mineral]
                if not paths:
                    raise ValueError("当前矿物的逐像元检查结果已释放，不能重复生成输出")
                with ExitStack() as stack:
                    data = {
                        key: stack.enter_context(rasterio.open(path, "r+"))
                        for key, path in paths.items()
                    }
                    source = data["raw"]
                    pixel_area = abs(source.transform.determinant)
                    records = {}
                    active = []
                    for group_id, (key, ordinal, finding) in self.groups.items():
                        if key != mineral or group_id not in selected:
                            continue
                        operation = selected[group_id]
                        records[group_id] = {
                            **operation,
                            "element": "alteration",
                            "actual_changed": False,
                            "pixel_count": 0,
                            "area_m2": 0.0,
                            "involved_area_m2": json.loads(
                                finding["measurements_json"]
                            )["area_m2"],
                            "measurements_json": finding["measurements_json"],
                            "group_id": group_id,
                            "_geometry": finding["_geometry"],
                        }
                        active.append((group_id, ordinal, finding, operation))
                    outputs = (
                        {
                            key: stack.enter_context(
                                create(
                                    paths["raw"].parent / (key + ".tif"),
                                    source.profile,
                                    dtype,
                                )
                            )
                            for key, dtype in {
                                "corrected": "uint8",
                                "weight": "float32",
                                "changes": "uint8",
                            }.items()
                        }
                        if operations is not None
                        else {}
                    )
                    retained = 0
                    for window in windows(source.profile):
                        raw = source.read(1, window=window)
                        corrected = raw.copy()
                        original_weights = data["weights"].read(1, window=window)
                        weights = original_weights.copy()
                        changed = np.zeros(raw.shape, dtype="uint8")
                        groups = data["groups"].read(1, window=window)
                        for group_id, ordinal, finding, operation in active:
                            cells = groups == ordinal
                            if operation["action"] == "exclude":
                                corrected[cells], weights[cells] = 0, 0
                            elif operation["action"] == "downweight":
                                weights[cells] = np.minimum(
                                    weights[cells], operation["weight"]
                                )
                            changed_cells = cells & (
                                (corrected != raw) | (weights != original_weights)
                            )
                            changed[changed_cells] = int(finding["rule_id"][-2:])
                            records[group_id]["pixel_count"] += int(changed_cells.sum())
                        for key, values in (
                            ("corrected", corrected),
                            ("weight", weights),
                            ("changes", changed),
                        ):
                            if key in outputs:
                                outputs[key].write(
                                    values.astype(outputs[key].dtypes[0], copy=False),
                                    1,
                                    window=window,
                                )
                        retained += int(corrected.sum())
                    for record in records.values():
                        record["actual_changed"] = bool(record["pixel_count"])
                        record["area_m2"] = record["pixel_count"] * pixel_area
                        actual.append(record)
                    quality = next(
                        row for row in self.quality if row["mineral"] == mineral
                    )
                    quality.update(
                        retained_pixels=retained, retained_area_m2=retained * pixel_area
                    )
                    if operations is None:
                        for suffix, key, label in [
                            (
                                "hits",
                                "hits",
                                "0=无问题;1=A-01;2=A-02;3=A-03;4=A-04;5=A-05",
                            ),
                            ("before", "raw", "0=未识别;1=识别"),
                            ("groups", "groups", "分组索引，见group_index.csv"),
                        ]:
                            publish(context, mineral, suffix, data[key], label)
                    else:
                        for suffix, label in [
                            ("corrected", "0=未识别;1=识别"),
                            ("weight", "证据权重0..1"),
                            ("changes", "0=未改;1..5=A-01..A-05"),
                        ]:
                            publish(context, mineral, suffix, outputs[suffix], label)
                for path in paths.values():
                    path.unlink(missing_ok=True)
                shutil.rmtree(paths["raw"].parent)
                self.minerals[mineral] = None
                gc.collect()
        write_table(
            context.output_path("alteration_summary.csv"),
            self.summaries,
            SUMMARY_FIELDS,
        )
        write_table(
            context.output_path("alteration_quality.csv"), self.quality, QUALITY_FIELDS
        )
        write_table(
            context.output_path("group_index.csv"),
            [
                {"group_id": group_id, "mineral": key, "ordinal": ordinal}
                for group_id, (key, ordinal, _) in self.groups.items()
            ],
            ["group_id", "mineral", "ordinal"],
        )
        self.workspace.cleanup()
        self.grids = None
        return actual

    def aggregate(self, transform, dimensions, epsg, allowed):
        result = np.zeros(dimensions, dtype="float32")
        with rasterio.Env(GDAL_CACHEMAX=GDAL_CACHE_MB * 1024 * 1024):
            for mineral, name in RASTERS.items():
                if name not in allowed:
                    continue
                with ExitStack() as stack:
                    source = stack.enter_context(
                        rasterio.open(self.context.input_path(mineral))
                    )
                    weights = open_weights(self.context, mineral, source, stack)
                    area = (
                        gpd.GeoSeries([self.area], crs=self.config["working_epsg"])
                        .to_crs(source.crs)
                        .iloc[0]
                    )
                    directory = stack.enter_context(
                        TemporaryDirectory(
                            prefix=".evidence-",
                            dir=Path(self.context.output_path("evidence.csv")).parent,
                        )
                    )
                    path = Path(directory) / "weighted.tif"
                    dtype = np.result_type(
                        "float32", weights.dtypes[0] if weights else "float32"
                    )
                    with create(path, source.profile, dtype) as target:
                        for window in windows(source.profile):
                            raw = read_raw(source, window, area)
                            values = raw.astype("float32") * read_weights(
                                weights, window, raw.shape
                            )
                            target.write(values, 1, window=window)
                    fraction = np.zeros(dimensions, dtype="float32")
                    with rasterio.open(path) as evidence:
                        reproject(
                            rasterio.band(evidence, 1),
                            fraction,
                            src_transform=source.transform,
                            src_crs=source.crs,
                            dst_transform=transform,
                            dst_crs=epsg,
                            resampling=Resampling.average,
                            warp_mem_limit=GDAL_CACHE_MB,
                        )
                    result += fraction
        return result
