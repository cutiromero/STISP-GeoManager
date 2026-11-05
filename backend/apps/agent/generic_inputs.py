"""Normalized working copies for the generic geology workflow.

Original uploads stay unchanged. Each copy keeps only the canonical fields the
multi-element operators read; absent optional inputs get explicit, labeled
stand-ins (map extent, empty fault layer, all-zero alteration raster).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from django.db import transaction

from apps.catalog.models import DataResource
from apps.compute.packages import ComputeError
from apps.core.storage import vector_geopackage_path

from .geology_generic import MINERALS, utm_epsg
from .workflow_resources import resolve_workflow_resource
from .workflow_uploads import register_vector

PLACEHOLDER_NAME = "未提供的蚀变识别结果（全零）"
MAX_PIXELS = 4000
LITHOLOGY_COLORS = json.loads(
    (Path(__file__).parent / "data" / "lithology_colors.json").read_text(
        encoding="utf-8"
    )
)["colors"]


def _read(resource):
    import geopandas as gpd

    return gpd.read_file(vector_geopackage_path(), layer=resource.storage_path)


def _text(series):
    return series.map(lambda v: "" if v is None or v != v else str(v).strip())


def _identifiers(frame, prefix):
    """Neutral IDs; the operators reject IDs that could carry evaluation labels."""
    return [f"{prefix}{index:05d}" for index in range(1, len(frame) + 1)]


def lithology_copy(frame, mapping, epsg):
    import geopandas as gpd
    import pandas as pd

    names = _text(frame[mapping["name"]])
    if names.eq("").all():
        raise ComputeError("地质图的地层或单元名称字段全部为空")
    data = {
        "feature_id": _identifiers(frame, "F"),
        "name": names.where(names.ne(""), "未命名单元"),
    }
    codes = _text(frame[mapping["geo_sym"]]) if mapping.get("geo_sym") else names
    data["geo_sym"] = codes.where(codes.ne(""), data["name"])
    if mapping.get("conf"):
        data["conf"] = pd.to_numeric(frame[mapping["conf"]], errors="coerce").clip(0, 1)
    return gpd.GeoDataFrame(data, geometry=frame.geometry.values, crs=frame.crs).to_crs(
        epsg
    )


def coverage_copy(frame, mapping, lithology):
    import geopandas as gpd
    from shapely.ops import unary_union

    if frame is None:
        area = unary_union(lithology.geometry).buffer(1.0)
        return gpd.GeoDataFrame(
            {"coverage_id": ["C00001"]}, geometry=[area], crs=lithology.crs
        )
    copy = gpd.GeoDataFrame(
        {"coverage_id": _identifiers(frame, "C")},
        geometry=frame.geometry.values,
        crs=frame.crs,
    ).to_crs(lithology.crs)
    if mapping.get("role"):
        roles = _text(frame[mapping["role"]]).str.casefold()
        copy["role"] = roles.where(roles.eq("exclusion"), "coverage").values
    return copy


def _area(coverage):
    from shapely.ops import unary_union

    if "role" in coverage:
        keep = coverage.loc[coverage.role != "exclusion", "geometry"]
        drop = coverage.loc[coverage.role == "exclusion", "geometry"]
        return unary_union(keep).difference(unary_union(drop))
    return unary_union(coverage.geometry)


def faults_copy(frame, coverage):
    import geopandas as gpd

    if frame is None:
        return gpd.GeoDataFrame({"line_id": []}, geometry=[], crs=coverage.crs), 0
    frame = frame.to_crs(coverage.crs)
    clipped = frame.geometry.intersection(_area(coverage))
    keep = ~clipped.is_empty & clipped.geom_type.str.contains("Line")
    data = {"line_id": _identifiers(frame, "S")}
    copy = gpd.GeoDataFrame(data, geometry=clipped.values, crs=coverage.crs)
    return copy.loc[keep.values].reset_index(drop=True), int((~keep).sum())


def units_override(frame, mapping):
    import pandas as pd

    codes = _text(frame[mapping["code"]])
    units, aliases = {}, {}
    for index, code in codes.items():
        if not code:
            continue
        unit = {}
        if mapping.get("category"):
            unit["category"] = _text(frame[mapping["category"]])[index] or None
        if mapping.get("age_ma"):
            age = pd.to_numeric(frame[mapping["age_ma"]][index], errors="coerce")
            unit["age_ma"] = None if pd.isna(age) else float(age)
        if mapping.get("group"):
            unit["group"] = _text(frame[mapping["group"]])[index] or None
        if mapping.get("favorable"):
            flag = _text(frame[mapping["favorable"]])[index].casefold()
            unit["favorable"] = flag in {"true", "1", "yes", "是", "有利"}
        units[code] = {key: value for key, value in unit.items() if value is not None}
        if mapping.get("name"):
            name = _text(frame[mapping["name"]])[index]
            if name:
                aliases[name] = code
    if not units:
        raise ComputeError("填图单元表没有可用的代号")
    return {"units": units, "aliases": aliases}


def placeholder_raster(user, workflow, coverage, resolution):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    from apps.raster.services.importer import import_raster_file

    west, south, east, north = coverage.total_bounds
    size = max(east - west, north - south)
    resolution = max(float(resolution), size / MAX_PIXELS)
    width = max(1, int(np.ceil((east - west) / resolution)))
    height = max(1, int(np.ceil((north - south) / resolution)))
    source = f"workflow-working:{workflow.id}:minerals"
    with tempfile.TemporaryDirectory(prefix="geomanager-wf-") as directory:
        path = Path(directory) / "placeholder.tif"
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=width,
            height=height,
            count=1,
            dtype="uint8",
            crs=coverage.crs,
            transform=from_origin(west, north, resolution, resolution),
        ) as target:
            target.write(np.zeros((1, height, width), dtype="uint8"))
        resource = import_raster_file(
            path,
            name=PLACEHOLDER_NAME,
            raster_kind="categorical",
            uploader_id=user.id,
            owner_only=True,
            resource_source=source,
        ).data_resource
    resource.maintainer, resource.is_compute_result = user, True
    resource.description = (
        "通用地质推理中未上传的蚀变类型，以全零栅格表示未提供识别结果"
    )
    resource.save()
    return resource


PALETTE = (
    "#7fb3d5",
    "#f5b041",
    "#82e0aa",
    "#f1948a",
    "#bb8fce",
    "#f7dc6f",
    "#76d7c4",
    "#e59866",
    "#85c1e9",
    "#c39bd3",
    "#a9dfbf",
    "#f8c471",
    "#d98880",
    "#73c6b6",
)
MAX_LEGEND_CLASSES = 60


def name_symbolization(frame, field="name"):
    """Colour units by name so map legends read as unit names, not codes."""
    names = sorted({str(v) for v in frame[field] if str(v).strip()})[
        :MAX_LEGEND_CLASSES
    ]
    return {
        "opacity": 85,
        "renderer": {
            "type": "uniqueValue",
            "field": field,
            "classes": [
                {
                    "id": f"unit-{index}",
                    "value": name,
                    "label": name,
                    "color": LITHOLOGY_COLORS.get(name, PALETTE[index % len(PALETTE)]),
                }
                for index, name in enumerate(names)
            ],
            "defaultClass": {"color": "#cbd5e1", "label": "其他"},
        },
        "line": {"lineColor": "#64748b", "lineWidth": 0.5},
    }


def style_lithology(resource):
    import geopandas as gpd

    visualization = dict(resource.default_visualization or {})
    data = gpd.read_file(
        vector_geopackage_path(),
        layer=resource.storage_path,
        columns=["name"],
        ignore_geometry=True,
    )
    visualization["symbolization"] = name_symbolization(data)
    if resource.default_visualization != visualization:
        resource.default_visualization = visualization
        resource.save(update_fields=["default_visualization", "updated_at"])


def _register_copies(workflow, user, uploads, lithology, coverage, faults, created):
    """Create the working resources, appending each to ``created`` as it lands."""
    marker = f"workflow-working:{workflow.id}:"
    with transaction.atomic():
        copies = {
            "lithology": register_vector(
                lithology,
                user=user,
                name="地质图（工作副本）",
                source=marker + "lithology",
                compute=True,
            ),
            "coverage": register_vector(
                coverage,
                user=user,
                name="研究区范围（工作副本）",
                source=marker + "coverage",
                compute=True,
            ),
            "faults": register_vector(
                faults,
                user=user,
                name="构造线（工作副本）",
                source=marker + "faults",
                geometry_type="LineString",
                compute=True,
            ),
        }
    created.extend(copies.values())
    visualization = dict(copies["lithology"].default_visualization or {})
    visualization["symbolization"] = name_symbolization(lithology)
    copies["lithology"].default_visualization = visualization
    copies["lithology"].save(update_fields=["default_visualization", "updated_at"])
    missing = [m for m in MINERALS if m not in uploads]
    rasters = {m: uploads[m] for m in MINERALS if m in uploads}
    if missing:
        resolution = workflow.parameters.get("grid_resolution_m", 100)
        placeholder = placeholder_raster(user, workflow, coverage, resolution)
        created.append(placeholder)
        rasters.update({m: placeholder.id for m in missing})
    return copies, rasters


def build_inputs(workflow, user, policy) -> None:
    from .demo_workflow import _save
    from .workflow import step

    if workflow.plan.get("workingCopies"):
        return
    uploads = workflow.plan["uploadInputs"]
    mapping = workflow.plan["confirmedMapping"]
    source = {
        role: resolve_workflow_resource(user, policy, identity, workflow)
        for role, identity in uploads.items()
    }
    original = _read(source["lithology"])
    bounds = original.to_crs(4326).total_bounds
    epsg = utm_epsg(bounds)
    lithology = lithology_copy(original, mapping["lithology"], epsg)
    coverage = coverage_copy(
        _read(source["coverage"]) if "coverage" in source else None,
        mapping.get("coverage", {}),
        lithology,
    )
    faults, dropped = faults_copy(
        _read(source["faults"]) if "faults" in source else None, coverage
    )
    created = []
    try:
        copies, rasters = _register_copies(
            workflow, user, uploads, lithology, coverage, faults, created
        )
        if "units" in source:
            from apps.catalog.nongeo import _resource_dataframe

            frame, _, _ = _resource_dataframe(source["units"], limit=5000, offset=0)
            workflow.plan["unitOverrides"] = units_override(frame, mapping["units"])
    except Exception:
        # A failed build leaves no half set behind; the retry starts from scratch.
        DataResource.objects.filter(pk__in=[r.id for r in created]).update(
            status="inactive"
        )
        raise
    inputs = {role: resource.id for role, resource in copies.items()}
    inputs.update(rasters, rules=workflow.plan["rulesResourceId"])
    provided = set(uploads)
    workflow.parameters = {
        **workflow.parameters,
        "working_epsg": epsg,
        "segment": "all" if provided & {"faults", *MINERALS} else "lithology",
    }
    workflow.plan.update(
        inputs=inputs,
        workingCopies={role: resource.id for role, resource in copies.items()},
        missingRoles=[
            m for m in ["faults", "coverage", "units", *MINERALS] if m not in provided
        ],
        droppedFaults=dropped,
        phase="inputs_ready",
    )
    workflow.resource_ids = sorted(set(inputs.values()) | set(uploads.values()))
    _save(workflow)
    step(
        workflow,
        "working_copies",
        action={"inputs": inputs, "workingEpsg": epsg, "droppedFaults": dropped},
        message=f"已生成工作副本，面积与距离按EPSG:{epsg}计算",
    )
