"""Pixel-preserving alteration inspection and deterministic group execution."""

import json
import math

import geopandas as gpd
import numpy as np
import rasterio
import shapely
from pyproj import CRS
from rasterio.features import rasterize
from rasterio.warp import Resampling, reproject
from scipy import ndimage
from shapely.geometry import box

from multi_io import RASTERS, digest, dump, geojson_geometry, write_table

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


def cog(path, values, profile, description):
    with rasterio.open(
        path,
        "w",
        driver="COG",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype=values.dtype,
        crs=profile["crs"],
        transform=profile["transform"],
        compress="DEFLATE",
        blocksize=256,
    ) as target:
        target.write(values, 1)
        target.set_band_description(1, description)
        target.update_tags(protocol="alteration-pixels-v1")


def burn(entries, profile, **options):
    if not entries:
        return np.zeros((profile["height"], profile["width"]), dtype="int32")
    return rasterize(
        entries,
        out_shape=(profile["height"], profile["width"]),
        transform=profile["transform"],
        **options,
    )


def component_summary(mask, profile, pixel_area):
    labels, count = ndimage.label(mask, structure=np.ones((3, 3)))
    sizes = np.bincount(labels.ravel())
    objects = ndimage.find_objects(labels)
    representatives = []
    for identity in sorted(range(1, count + 1), key=lambda key: (-sizes[key], key))[:3]:
        rows, columns = objects[identity - 1]
        bounds = pixel_bounds(
            rows.start, columns.start, rows.stop, columns.stop, profile
        )
        representatives.append(
            {"bbox": bounds, "area_m2": int(sizes[identity]) * pixel_area}
        )
    rows, columns = np.where(mask)
    bounds = pixel_bounds(
        rows.min(), columns.min(), rows.max() + 1, columns.max() + 1, profile
    )
    return count, bounds, representatives


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


class RasterAlterations:
    def __init__(self, context, config, area):
        self.context, self.config, self.area = context, config, area
        self.minerals, self.groups, self.summaries, self.quality = {}, {}, [], []
        self.snapshot = ""
        self.alt = np.array(list(RASTERS.values()))

    def __len__(self):
        return len(self.summaries)

    def inspect(self, lithology, rules, units, snapshot):
        self.snapshot = snapshot
        findings = []
        for mineral, name in RASTERS.items():
            with rasterio.open(self.context.input_path(mineral)) as source:
                profile = source.profile.copy()
                crs = CRS.from_user_input(source.crs)
                if not crs.is_projected or any(
                    abs(axis.unit_conversion_factor - 1) > 1e-9
                    for axis in crs.axis_info[:2]
                ):
                    raise ValueError(
                        "蚀变逐像元面积判断需要米制投影栅格，请先重投影输入"
                    )
                values = source.read(1, masked=True)
                valid = ~np.ma.getmaskarray(values)
                if not np.isin(values.data[valid], [0, 1]).all():
                    raise ValueError("蚀变输入必须为0/1栅格：" + mineral)
                raw = valid & (values.data == 1)
            mask = (
                burn(
                    [
                        (
                            self.area
                            if lithology.crs == crs
                            else gpd.GeoSeries([self.area], crs=lithology.crs)
                            .to_crs(crs)
                            .iloc[0],
                            1,
                        )
                    ],
                    profile,
                    dtype="uint8",
                )
                > 0
            )
            raw &= mask
            weights = np.ones(raw.shape, dtype="float32")
            try:
                weight_path = self.context.input_path(mineral + "_weight")
            except KeyError:
                weight_path = None
            if weight_path:
                with rasterio.open(weight_path) as source:
                    if (
                        source.crs != profile["crs"]
                        or source.transform != profile["transform"]
                        or source.shape != raw.shape
                    ):
                        raise ValueError("蚀变权重与识别网格不一致")
                    weights = source.read(1)
                if (
                    not np.isfinite(weights).all()
                    or ((weights < 0) | (weights > 1)).any()
                ):
                    raise ValueError("蚀变权重必须在0和1之间")
            pixel_area = abs(profile["transform"].determinant)
            if not math.isfinite(pixel_area) or pixel_area <= 0:
                raise ValueError("蚀变网格像元面积无效")
            local = lithology.to_crs(crs)
            codes = sorted(set(local.geo_sym.astype(str)))
            identities = {code: index + 1 for index, code in enumerate(codes)}
            entries = [
                (geometry, identities[str(code)])
                for code, geometry in zip(local.geo_sym, local.geometry)
            ]
            unit_grid = burn(entries, profile, dtype="int32")
            touched = np.zeros(raw.shape, dtype="uint16")
            for code in codes:
                polygons = local.loc[local.geo_sym.astype(str) == code].geometry
                touched += burn(
                    [(geometry, 1) for geometry in polygons],
                    profile,
                    dtype="uint8",
                    all_touched=True,
                )
            boundary = touched > 1
            boundary_rows, boundary_columns = np.where(boundary)
            if len(boundary_rows):
                transform = profile["transform"]
                if transform.b or transform.d:
                    raise ValueError("逐像元边界统计暂不支持旋转网格，请先转为北向网格")
                left = transform.c + boundary_columns * transform.a
                top = transform.f + boundary_rows * transform.e
                pixels = shapely.box(
                    np.minimum(left, left + transform.a),
                    np.minimum(top, top + transform.e),
                    np.maximum(left, left + transform.a),
                    np.maximum(top, top + transform.e),
                )
                intersected = np.zeros(len(pixels), dtype="uint16")
                for code in codes:
                    geometry = shapely.union_all(
                        local.loc[local.geo_sym.astype(str) == code].geometry
                    )
                    intersected += (
                        shapely.area(shapely.intersection(pixels, geometry))
                        > pixel_area * 1e-10
                    )
                boundary[boundary_rows, boundary_columns] = intersected > 1
            hits = np.zeros(raw.shape, dtype="uint8")
            group_grid = np.zeros(raw.shape, dtype="uint32")
            hydrothermal = np.zeros(raw.shape, dtype=bool)
            for code in codes + [""]:
                index = identities.get(code, 0)
                group = units.get(code, {}).get("group", "unknown")
                selected = raw & (unit_grid == index)
                if (
                    mineral in {"calcite", "dolomite"}
                    and code
                    and group
                    not in {"carbonate", "carbonate_interbed", "loose", "unknown", ""}
                ):
                    hydrothermal |= selected
                small = np.zeros(raw.shape, dtype=bool)
                if "A-05" in rules:
                    labels, _ = ndimage.label(selected, structure=np.ones((3, 3)))
                    sizes = np.bincount(labels.ravel())
                    threshold = (
                        rules["A-05"]["params"].get("min_area_m2", 2600) / pixel_area
                    )
                    small = selected & (sizes[labels] < threshold)
                for rule_id in RULE_PRIORITY:
                    if rule_id not in rules or self.config["segment"] not in {
                        "all",
                        "alteration",
                    }:
                        continue
                    action, matches = {
                        "A-01": (
                            "exclude",
                            group == "carbonate" and mineral in {"calcite", "dolomite"},
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
                    candidate = selected & (hits == 0)
                    if rule_id == "A-05":
                        candidate &= small
                    for mixed in (False, True):
                        cells = candidate & (boundary == mixed)
                        if not cells.any():
                            continue
                        rule = rules[rule_id]
                        group_id = (
                            "AG-"
                            + digest(
                                [
                                    "alteration-pixels-v1",
                                    rule_id,
                                    mineral,
                                    code,
                                    group,
                                    mixed,
                                    action,
                                ]
                            )[:24]
                        )
                        count = int(cells.sum())
                        components, bounds, representatives = component_summary(
                            cells, profile, pixel_area
                        )
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
                            "allowed_actions_json": dump(
                                ["keep", "review", "downweight", "exclude"]
                            ),
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
                            "snapshot_hash": snapshot,
                            "geometry_json": geojson_geometry(
                                geometry, self.config["working_epsg"]
                            ),
                            "_geometry": geometry,
                        }
                        findings.append(finding)
                        ordinal = len(self.groups) + 1
                        self.groups[group_id] = (mineral, ordinal, finding)
                        hits[cells] = int(rule_id[-2:])
                        group_grid[cells] = ordinal
            self.minerals[mineral] = dict(
                raw=raw,
                weights=weights,
                profile=profile,
                hits=hits,
                groups=group_grid,
                pixel_area=pixel_area,
            )
            original, hit = int(raw.sum()), int((hits > 0).sum())
            positive = int(hydrothermal.sum())
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
                            int((raw & boundary).sum()),
                        ],
                    )
                )
            )
        return findings, self

    def outputs(self, context, operations=None):
        actual = []
        selected = {row["feature_id"]: row for row in operations or []}
        for mineral, data in self.minerals.items():
            corrected = data["raw"].astype("uint8")
            weights = data["weights"].copy()
            changed = np.zeros(corrected.shape, dtype="uint8")
            for group_id, (key, ordinal, finding) in self.groups.items():
                if key != mineral or group_id not in selected:
                    continue
                operation = selected[group_id]
                cells = data["groups"] == ordinal
                action = operation["action"]
                if action == "exclude":
                    corrected[cells], weights[cells] = 0, 0
                elif action == "downweight":
                    weights[cells] = np.minimum(weights[cells], operation["weight"])
                changed_cells = cells & (
                    (corrected != data["raw"]) | (weights != data["weights"])
                )
                changed[changed_cells] = int(finding["rule_id"][-2:])
                measurements = json.loads(finding["measurements_json"])
                actual.append(
                    {
                        **operation,
                        "element": "alteration",
                        "actual_changed": bool(changed_cells.any()),
                        "pixel_count": int(changed_cells.sum()),
                        "area_m2": int(changed_cells.sum()) * data["pixel_area"],
                        "involved_area_m2": measurements["area_m2"],
                        "measurements_json": finding["measurements_json"],
                        "group_id": group_id,
                        "_geometry": finding["_geometry"],
                    }
                )
            for suffix, values, label in [
                ("hits", data["hits"], "0=无问题;1=A-01;2=A-02;3=A-03;4=A-04;5=A-05"),
                ("before", data["raw"].astype("uint8"), "0=未识别;1=识别"),
                ("groups", data["groups"], "分组索引，见group_index.csv"),
                ("corrected", corrected, "0=未识别;1=识别"),
                ("weight", weights.astype("float32"), "证据权重0..1"),
                ("changes", changed, "0=未改;1..5=A-01..A-05"),
            ]:
                if operations is None and suffix in {"corrected", "weight", "changes"}:
                    continue
                if operations is not None and suffix in {"hits", "groups", "before"}:
                    continue
                cog(
                    context.output_path(f"{mineral}_{suffix}.tif"),
                    values,
                    data["profile"],
                    label,
                )
            quality = next(row for row in self.quality if row["mineral"] == mineral)
            quality.update(
                retained_pixels=int(corrected.sum()),
                retained_area_m2=int(corrected.sum()) * data["pixel_area"],
            )
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
        return actual

    def aggregate(self, transform, dimensions, epsg, allowed):
        result = np.zeros(dimensions, dtype="float32")
        for mineral, data in self.minerals.items():
            if RASTERS[mineral] not in allowed:
                continue
            fraction = np.zeros(dimensions, dtype="float32")
            reproject(
                data["raw"].astype("float32") * data["weights"],
                fraction,
                src_transform=data["profile"]["transform"],
                src_crs=data["profile"]["crs"],
                dst_transform=transform,
                dst_crs=epsg,
                resampling=Resampling.average,
            )
            result += fraction
        return result
