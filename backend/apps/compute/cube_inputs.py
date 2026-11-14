"""Source-bound native SeasFire observations materialized as temporal input stacks."""

import hashlib
import itertools
import json
import math

from apps.core.storage import research_path
from .packages import ComputeError
from .native_cube_reader import Cube, PRODUCTS


def is_native_cube(resource):
    return resource.data_type == "raster" and resource.file_format.upper() == "ZARR"


def cube_root(resource):
    path = research_path("raster", resource.storage_path)
    if path.suffix != ".zarr" or not path.is_dir():
        raise ComputeError("原生Zarr目录不存在或路径无效")
    return path


def source_dependencies(root, variant=None):
    metadata = json.loads((root / ".zmetadata").read_text())["metadata"]
    names = ["time", "latitude", "longitude"]
    if variant:
        names.append(variant["product"])
        mask = PRODUCTS[variant["product"]]["mask"]
        if mask:
            names.append(mask)
    paths = []
    for name in names:
        spec = metadata[name + "/.zarray"]
        shape = spec["shape"]
        chunks = spec["chunks"]
        separator = spec.get("dimension_separator", ".")
        if separator not in (".", "/"):
            raise ComputeError("Zarr分块命名无效")
        paths.extend([root / name / ".zarray", root / name / ".zattrs"])
        if variant and name == variant["product"]:
            row, col, height, width = variant["window"]
            first = min(variant["groups"][0])
            last = max(variant["groups"][-1])
            starts = [first, row, col]
            ends = [last + 1, row + height, col + width]
            ranges = [
                range(begin // chunk, math.ceil(end / chunk))
                for begin, end, chunk in zip(starts, ends, chunks)
            ]
        else:
            ranges = [
                range(math.ceil(length / chunk)) for length, chunk in zip(shape, chunks)
            ]
        for indices in itertools.product(*ranges):
            paths.append(root / name / separator.join(str(index) for index in indices))
    return sorted(set(paths))


def fingerprint(root, variant):
    files = [root / ".zmetadata", *source_dependencies(root, variant)]
    records = []
    for path in files:
        if not path.is_file() or path.is_symlink():
            raise ComputeError("原生立方体分块缺失或类型变化")
        stat = path.stat()
        records.append(
            [
                str(path.relative_to(root)),
                stat.st_ino,
                stat.st_size,
                stat.st_mtime_ns,
                stat.st_ctime_ns,
            ]
        )
    return hashlib.sha256(json.dumps(records).encode()).hexdigest()


def candidate_metadata(resource):
    cube = Cube(cube_root(resource))
    west = float(cube.longitude[0] - 0.125)
    north = float(cube.latitude[0] + 0.125)
    return {
        "bands": 0,
        "crs": "EPSG:4326",
        "bounds": [
            west,
            north - len(cube.latitude) * 0.25,
            west + len(cube.longitude) * 0.25,
            north,
        ],
        "nativeCube": True,
        "fields": [],
        "cubeTimeCount": len(cube.dates),
    }


def prepare_metadata(resource, spec, info, parameters):
    config = spec.get("raster", {}).get("cube")
    if not config or config.get("family") != "seasfire_observation_v04":
        raise ComputeError("原生Zarr须使用声明时间与变量的观测算子")
    try:
        root = cube_root(resource)
        cube = Cube(root)
        bounds = [parameters[key] for key in spec["raster"]["window"]]
        plan = cube.plan(
            parameters[config["variableParameter"]],
            parameters[config["timeParameter"]],
            bounds,
            parameters[config["historyParameter"]],
        )
        plan["sourceFingerprint"] = fingerprint(root, plan)
    except (ValueError, KeyError, TypeError) as error:
        raise ComputeError(str(error) or "原生观测输入无效") from error
    row, col, height, width = plan["window"]
    bands = len(plan["groups"])
    transform = [
        float(cube.longitude[col] - 0.125),
        0.25,
        0,
        float(cube.latitude[row] + 0.125),
        0,
        -0.25,
    ]
    return {
        **info,
        "bands": bands,
        "sizeBytes": height * width * bands * 8 + 65536,
        "cubeInput": plan,
        "bounds": [
            transform[0],
            transform[3] - 0.25 * height,
            transform[0] + 0.25 * width,
            transform[3],
        ],
        "rasterMetadata": {
            "source": "native_cube_temporal_snapshot",
            "size": [width, height],
            "geoTransform": transform,
            "coordinateSystem": "EPSG:4326",
            "linearUnitMeters": None,
            "bands": [
                {
                    "band": index + 1,
                    "type": "float32",
                    "description": period[0],
                    "unit": plan["unit"],
                }
                for index, period in enumerate(plan["periods"])
            ],
        },
    }


def materialize(resource, target, plan):
    import numpy as np
    from osgeo import gdal, osr

    root = cube_root(resource)
    if fingerprint(root, plan) != plan["sourceFingerprint"]:
        raise ComputeError("原始时空分块已变化，请重新预检")
    cube = Cube(root)
    current = cube.plan(plan["product"], plan["index"], plan["bounds"], plan["history"])
    if current != {k: v for k, v in plan.items() if k != "sourceFingerprint"}:
        raise ComputeError("原始时间或格网定义已变化，请重新预检")
    frames, report = cube.observation(
        plan["product"],
        plan["index"],
        plan["bounds"],
        plan["history"],
        return_frames=True,
    )
    height, width = frames.shape[1:]
    output = gdal.GetDriverByName("GTiff").Create(
        str(target),
        width,
        height,
        len(frames),
        gdal.GDT_Float32,
        options=["TILED=YES", "COMPRESS=DEFLATE"],
    )
    reference = osr.SpatialReference()
    reference.ImportFromEPSG(4326)
    output.SetProjection(reference.ExportToWkt())
    output.SetGeoTransform(report["grid"]["transform"])
    for index, frame in enumerate(frames, 1):
        band = output.GetRasterBand(index)
        band.SetNoDataValue(-9999)
        band.WriteArray(np.where(np.isfinite(frame), frame, -9999))
        band.SetDescription(report["series"][index - 1]["observedStart"])
    output.SetMetadataItem("stisp_input_semantics", "temporal_observation_stack_v1")
    output.SetMetadataItem("stisp_cube_slice", json.dumps(report, ensure_ascii=False))
    output.FlushCache()
    output = None
    if fingerprint(root, plan) != plan["sourceFingerprint"]:
        target.unlink(missing_ok=True)
        raise ComputeError("原始时空分块在准备期间变化")
