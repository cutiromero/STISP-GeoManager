"""Bounded, source-grid raster windows declared by published operator ports."""

from copy import deepcopy
import math

from .packages import ComputeError

MAX_WINDOW_PIXELS = 4_194_304


def windowed_metadata(spec, info, parameters):
    names = (spec.get("raster") or {}).get("window")
    if not names:
        return info
    from .preflight import gap
    from affine import Affine
    from rasterio.windows import from_bounds

    try:
        west, south, east, north = [parameters[key] for key in names]
        if any(
            type(v) not in (int, float) or not math.isfinite(v)
            for v in (west, south, east, north)
        ) or not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError()
        metadata = info["rasterMetadata"]
        if info["crs"] != "EPSG:4326":
            raise ValueError()
        transform = metadata["geoTransform"]
        if transform[2] or transform[4] or transform[1] <= 0 or transform[5] >= 0:
            raise ValueError()
        affine = Affine.from_gdal(*transform)
        region = from_bounds(west, south, east, north, affine)
        # Pixel centres determine inclusion at the requested geographic boundary.
        x = math.ceil(region.col_off - 0.5)
        y = math.ceil(region.row_off - 0.5)
        right = math.ceil(region.col_off + region.width - 0.5)
        bottom = math.ceil(region.row_off + region.height - 0.5)
        width, height = right - x, bottom - y
        if (
            x < 0
            or y < 0
            or right > metadata["size"][0]
            or bottom > metadata["size"][1]
            or min(width, height) < 1
            or (
                width * height > MAX_WINDOW_PIXELS
                and not (spec.get("raster") or {}).get("streaming")
            )
        ):
            raise ValueError()
    except (KeyError, ValueError, TypeError, OverflowError) as error:
        raise ComputeError(
            "研究区须位于原始WGS84影像范围内，且不超过4194304像元",
            gaps=[
                gap(
                    "RASTER_WINDOW",
                    spec["key"],
                    "adjust_parameters",
                    expected={"crs": "EPSG:4326", "maxPixels": MAX_WINDOW_PIXELS},
                )
            ],
        ) from error
    value = deepcopy(info)
    value["rasterWindow"] = [x, y, width, height]
    if (spec.get("raster") or {}).get("streaming"):
        value["streamingRaster"] = True
    value["sourceSizeBytes"] = info["sizeBytes"]
    # Budget the uncompressed window, rather than the compressed continental file.
    value["sizeBytes"] = width * height * len(metadata["bands"]) * 8 + 65536
    if value.get("streamingRaster"):
        value["sizeBytes"] = (
            min(width, 256) * min(height, 256) * len(metadata["bands"]) * 8 + 65536
        )
    value["rasterMetadata"]["size"] = [width, height]
    value["rasterMetadata"]["geoTransform"] = list(
        (affine * Affine.translation(x, y)).to_gdal()
    )
    return value


def whole_grid_metadata(info):
    """Describe a native full-grid view without geographic bounds or resampling."""
    value = deepcopy(info)
    width, height = value["rasterMetadata"]["size"]
    bands = len(value["rasterMetadata"]["bands"])
    value.update(
        rasterWindow=[0, 0, width, height],
        streamingRaster=True,
        sourceSizeBytes=info["sizeBytes"],
        sizeBytes=min(width, 256) * min(height, 256) * bands * 8 + 65536,
    )
    return value


def materialize_window(resource, target, window):
    import rasterio
    from rasterio.windows import Window
    from apps.core.storage import raster_source_path
    from apps.raster.models import RasterDataset

    dataset = RasterDataset.objects.get(data_resource=resource, status="ready")
    with rasterio.open(raster_source_path(dataset.source_relative_path)) as source:
        x, y, width, height = window
        region = Window(x, y, width, height)
        profile = {
            **source.profile,
            "driver": "GTiff",
            "width": width,
            "height": height,
            "transform": source.window_transform(region),
            "tiled": True,
            "blockxsize": 256,
            "blockysize": 256,
            "compress": "deflate",
        }
        with (
            rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True, GDAL_PAM_ENABLED="NO"),
            rasterio.open(target, "w", **profile) as output,
        ):
            output.update_tags(**source.tags())
            for band in range(1, source.count + 1):
                if source.descriptions[band - 1]:
                    output.set_band_description(band, source.descriptions[band - 1])
            output.scales = source.scales
            output.offsets = source.offsets
            for _, block in output.block_windows(1):
                selected = Window(
                    x + block.col_off, y + block.row_off, block.width, block.height
                )
                values = source.read(window=selected, masked=True)
                output.write(
                    values.filled(source.nodata if source.nodata is not None else 0),
                    window=block,
                )
                output.write_mask(
                    (
                        ~values.mask.any(axis=0)
                        if values.mask.ndim
                        else source.dataset_mask(window=selected) > 0
                    ).astype("uint8")
                    * 255,
                    window=block,
                )


def materialize_streaming_window(resource, target, window):
    """Freeze an exact source-grid view; source identities remain in stage_version."""
    from apps.core.storage import raster_source_path
    from apps.raster.models import RasterDataset
    from apps.raster.services.gdal_ops import run_gdal_command

    dataset = RasterDataset.objects.get(data_resource=resource, status="ready")
    source = raster_source_path(dataset.source_relative_path)
    run_gdal_command(
        [
            "gdal_translate",
            "-of",
            "VRT",
            "-srcwin",
            *[str(value) for value in window],
            str(source),
            str(target),
        ]
    )
    import xml.etree.ElementTree as etree

    tree = etree.parse(target)
    for entry in tree.iter("SourceFilename"):
        if entry.get("relativeToVRT") == "1":
            resolved = (target.parent / entry.text).resolve()
            if not resolved.is_relative_to(raster_source_path("").resolve()):
                raise ValueError("流式输入源路径超出当前项目原始资料目录")
            entry.text = str(resolved)
            entry.set("relativeToVRT", "0")
    # The descriptor checksum must also change if a referenced source changes.
    # A VRT with identical XML paths is not an immutable pixel snapshot.
    from .input_versions import source_version
    import hashlib
    import json

    fingerprint = hashlib.sha256(
        json.dumps(source_version(resource), sort_keys=True).encode()
    ).hexdigest()
    tree.getroot().append(etree.Comment("source-version-sha256=" + fingerprint))
    tree.write(target, encoding="UTF-8")


def default_extent_parameters(
    manifest, bindings, parameters, user, candidate_cache, resource_cache
):
    """Resolve missing spatial parameters from authorized original input footprints."""
    from apps.catalog.models import DataResource
    from apps.catalog.permissions import user_can_access
    from apps.projects.context import selected_project_id
    from .data import candidate

    ports = [
        port
        for port in manifest["inputs"]
        if (port.get("raster") or {}).get("defaultExtent")
    ]
    if not ports:
        return parameters
    keys = ports[0]["raster"]["window"]
    missing = [key for key in keys if key not in parameters]
    if not missing:
        return parameters
    if len(missing) != 4 or any(port["raster"]["window"] != keys for port in ports):
        raise ComputeError("请完整设置研究区四界，或全部省略使用数据全域")
    bounds = []
    for port in ports:
        identity = bindings.get(port["key"])
        resource = DataResource.objects.filter(
            pk=identity, status="active", project_tag_id=selected_project_id()
        ).first()
        if resource is None or not user_can_access(resource, user):
            raise ComputeError("当前用户无权使用所选原始资料")
        resource_cache[identity] = resource
        info = candidate(resource, raster_metadata=True, semantic_metadata=True)
        candidate_cache[identity] = info
        geometry = info.get("rasterMetadata") or {}
        if geometry.get("geoTransform") and info.get("crs") == "EPSG:4326":
            transform = geometry["geoTransform"]
            width, height = geometry["size"]
            footprint = [
                transform[0],
                transform[3] + height * transform[5],
                transform[0] + width * transform[1],
                transform[3],
            ]
        else:
            footprint = info.get("bounds")
        if not isinstance(footprint, list) or len(footprint) != 4:
            raise ComputeError("所选资料尚无完整空间覆盖范围")
        bounds.append(footprint)
    west, south = max(row[0] for row in bounds), max(row[1] for row in bounds)
    east, north = min(row[2] for row in bounds), min(row[3] for row in bounds)
    if west >= east or south >= north:
        raise ComputeError("所选资料没有共同覆盖范围")
    return {**parameters, **dict(zip(keys, [west, south, east, north]))}


def validate_temporal_inputs(manifest, resources):
    """Check declared seasonal feature slots against registered observation time."""
    from apps.catalog.models import ResourceObservationMetadata

    ports = {
        port["key"]: port
        for port in manifest["inputs"]
        if (port.get("raster") or {}).get("months")
    }
    if not ports:
        return
    dates = {
        row.resource_id: row.starts_at
        for row in ResourceObservationMetadata.objects.filter(
            resource_id__in=[resource.pk for _, resource, _ in resources]
        )
    }
    years = set()
    for key, resource, _ in resources:
        if key not in ports:
            continue
        contract = ports[key]["raster"]
        day = dates.get(resource.pk)
        if day is None or day.month not in contract["months"]:
            raise ComputeError(ports[key]["label"] + "须使用模型声明月份的已登记影像")
        if contract.get("sameYear"):
            years.add(day.year)
    if len(years) > 1:
        raise ComputeError("该年度联合模型的输入影像须来自同一观测年")


def streaming_output_grid(task, manifest):
    """Only configured native streaming jobs may return source-grid-sized rasters."""
    if manifest.get("runtime") not in {
        "python-geospatial-ml-v1",
        "python-geospatial-gpu-v1",
    }:
        return None
    port = next(
        (
            row
            for row in manifest["inputs"]
            if (row.get("raster") or {}).get("streaming")
        ),
        None,
    )
    if port is None:
        return None
    record = task.input_records.get(key=port["key"])
    snapshot = record.snapshot
    if not snapshot.get("streamingRaster") or not snapshot.get("fixedAtExecution"):
        raise ComputeError("全域输出检查缺少冻结原始网格")
    metadata = snapshot["rasterMetadata"]
    return {
        "size": metadata["size"],
        "bands": len(metadata["bands"]),
        "geoTransform": metadata["geoTransform"],
        "crs": snapshot["crs"],
    }
