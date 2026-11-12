"""Normalized working copies for the generic geology workflow.

Original uploads stay unchanged. Each copy keeps only the canonical fields the
multi-element operators read; absent optional inputs get explicit, labeled
stand-ins (map extent, empty fault layer, all-zero alteration raster).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from apps.catalog.models import DataResource
from apps.compute.packages import ComputeError
from apps.core.storage import vector_geopackage_path

from .geology_generic import MINERALS, utm_epsg
from .workflow_resources import resolve_workflow_resource
from .workflow_uploads import register_vector
from .workflow_cancellation import check_cancelled
from .color_library import lithology_colors

PLACEHOLDER_NAME = "未提供的蚀变识别结果（全零）"
MAX_PIXELS = 4000
LITHOLOGY_COLORS = lithology_colors()


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
    import pandas as pd

    if frame is None:
        return gpd.GeoDataFrame(
            {"line_id": pd.Series(dtype="str")}, geometry=[], crs=coverage.crs
        ), 0
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


MAX_LEGEND_CLASSES = 60


def name_symbolization(frame, field="name"):
    """Colour units by name so map legends read as unit names, not codes."""
    from .result_colors import category_style

    names = sorted({str(v) for v in frame[field] if str(v).strip()})[
        :MAX_LEGEND_CLASSES
    ]
    style, _ = category_style(field, names)
    return style


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


def _register_copies(
    workflow, user, uploads, lithology, coverage, faults, created, *, sources=None
):
    """Create the working resources, appending each to ``created`` as it lands."""
    marker = f"workflow-working:{workflow.id}:"
    copies = {}
    for role, frame, name in (
        ("lithology", lithology, "地质图（工作副本）"),
        ("coverage", coverage, "研究区范围（工作副本）"),
        ("faults", faults, "构造线（工作副本）"),
    ):
        check_cancelled(workflow)
        resource = register_vector(
            frame,
            user=user,
            name=name,
            source=marker + role,
            compute=True,
            **({"geometry_type": "LineString"} if role == "faults" else {}),
        )
        created.append(resource)
        copies[role] = resource
    check_cancelled(workflow)
    visualization = dict(copies["lithology"].default_visualization or {})
    visualization["symbolization"] = name_symbolization(lithology)
    copies["lithology"].default_visualization = visualization
    copies["lithology"].save(update_fields=["default_visualization", "updated_at"])
    from .alteration_stack import supports_stack, prepare_stack

    if supports_stack(workflow, user):
        prepared = prepare_stack(workflow, user, sources, coverage)
        created.append(prepared)
        return copies, {"alteration_stack": prepared.pk}
    if any(role.startswith("alterations") for role in uploads):
        raise ComputeError("当前地质算子尚未发布可变类别输入版本，请先完成算子升级")
    missing = [m for m in MINERALS if m not in uploads]
    rasters = {m: uploads[m] for m in MINERALS if m in uploads}
    if missing:
        check_cancelled(workflow)
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
    check_cancelled(workflow)
    uploads = {
        role: workflow.plan.get("effectiveInputs", {}).get(role, identity)
        for role, identity in workflow.plan["uploadInputs"].items()
    }
    mapping = workflow.plan["confirmedMapping"]
    source = {
        role: resolve_workflow_resource(user, policy, identity, workflow)
        for role, identity in uploads.items()
    }
    original = _read(source["lithology"])
    check_cancelled(workflow)
    bounds = original.to_crs(4326).total_bounds
    epsg = utm_epsg(bounds)
    lithology = lithology_copy(original, mapping["lithology"], epsg)
    check_cancelled(workflow)
    coverage = coverage_copy(
        _read(source["coverage"]) if "coverage" in source else None,
        mapping.get("coverage", {}),
        lithology,
    )
    check_cancelled(workflow)
    faults, dropped = faults_copy(
        _read(source["faults"]) if "faults" in source else None, coverage
    )
    check_cancelled(workflow)
    created = []
    try:
        copies, rasters = _register_copies(
            workflow,
            user,
            uploads,
            lithology,
            coverage,
            faults,
            created,
            sources=source,
        )
        if "units" in source:
            from apps.catalog.nongeo import _resource_dataframe

            frame, _, _ = _resource_dataframe(source["units"], limit=5000, offset=0)
            workflow.plan["unitOverrides"] = units_override(frame, mapping["units"])
        check_cancelled(workflow)
    except Exception:
        # A failed build leaves no half set behind; the retry starts from scratch.
        DataResource.objects.filter(pk__in=[r.id for r in created]).update(
            status="inactive"
        )
        raise
    inputs = {role: resource.id for role, resource in copies.items()}
    inputs.update(rasters, rules=workflow.plan["rulesResourceId"])
    provided = set(uploads)
    optional_roles = ["faults", "coverage", "units"]
    if "alteration_stack" in rasters:
        if not any(
            role in MINERALS or role.startswith("alterations") for role in provided
        ):
            optional_roles.append("alterations")
    else:
        optional_roles.extend(MINERALS)
    workflow.parameters = {
        **workflow.parameters,
        "working_epsg": epsg,
        "segment": "all"
        if "faults" in provided
        or any(role in MINERALS or role.startswith("alterations") for role in provided)
        else "lithology",
    }
    workflow.plan.update(
        inputs=inputs,
        workingCopies={role: resource.id for role, resource in copies.items()},
        missingRoles=[role for role in optional_roles if role not in provided],
        droppedFaults=dropped,
        phase="inputs_ready",
    )
    workflow.resource_ids = sorted(set(inputs.values()) | set(uploads.values()))
    _save(workflow)
    if workflow.cancel_requested:
        DataResource.objects.filter(pk__in=[r.id for r in created]).update(
            status="inactive"
        )
        raise ComputeError("任务已停止", 409)
    step(
        workflow,
        "working_copies",
        action={"inputs": inputs, "workingEpsg": epsg, "droppedFaults": dropped},
        message=f"已生成工作副本，面积与距离按EPSG:{epsg}计算",
    )
    from .review_map_warmup import warm_review_background

    warm_review_background(workflow.id, [copies["lithology"].id, copies["faults"].id])
