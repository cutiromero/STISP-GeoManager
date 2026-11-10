"""Domain-neutral class masks and raster collections; source files stay read-only.

This module is also copied verbatim into the registered isolated adapter packages.
It does not import Django or resolve platform files: callers provide authorized paths.
"""

from contextlib import ExitStack
import math

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import (
    calculate_default_transform,
    reproject,
    Resampling,
)

SEMANTICS = "class_mask_stack_v1"
MAX_CLASSES = 64
MAX_EDGE = 4000


def class_label(value):
    value = str(value).strip()
    if not value or len(value) > 160 or "\x00" in value:
        raise ValueError("类别名称须为1至160字的非空文字")
    return value


def grid(bounds, crs, resolution):
    west, south, east, north = map(float, bounds)
    if (
        not math.isfinite(resolution)
        or resolution <= 0
        or not all(math.isfinite(v) for v in bounds)
        or east <= west
        or north <= south
    ):
        raise ValueError("目标网格范围或分辨率无效")
    width, height = (
        max(1, math.ceil((east - west) / resolution)),
        max(1, math.ceil((north - south) / resolution)),
    )
    if max(width, height) > MAX_EDGE:
        raise ValueError(
            f"目标网格超过{MAX_EDGE}像素边长，请明确选择更大的分辨率或缩小范围"
        )
    return {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "transform": from_origin(west, north, resolution, resolution),
        "crs": crs,
        "compress": "DEFLATE",
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
    }


def vector_class_masks(path, output, category_field, *, resolution=100, target_epsg=0):
    import geopandas as gpd

    frame = gpd.read_file(path)
    if frame.crs is None or category_field not in frame.columns or frame.empty:
        raise ValueError("分类矢量需要真实坐标系、非空要素及已确认的类别字段")
    if (
        frame[category_field].isna().any()
        or frame.geometry.isna().any()
        or frame.geometry.is_empty.any()
        or not frame.geometry.is_valid.all()
    ):
        raise ValueError("存在缺失类别、空或无效几何，请先通过已登记的修复工具处理")
    labels = frame[category_field].map(class_label)
    names = sorted(set(labels))
    if len(names) > MAX_CLASSES:
        raise ValueError(f"分类数量超过本次{MAX_CLASSES}类资源边界，请筛选或分批处理")
    if not target_epsg:
        if frame.crs.is_projected and all(
            abs(axis.unit_conversion_factor - 1) < 1e-9
            for axis in frame.crs.axis_info[:2]
        ):
            target_epsg = frame.crs
        else:
            west, south, east, north = frame.to_crs(4326).total_bounds
            target_epsg = (32600 if (south + north) / 2 >= 0 else 32700) + min(
                60, max(1, int(((west + east) / 2 + 180) // 6) + 1)
            )
    projected = frame.to_crs(target_epsg)
    profile = grid(projected.total_bounds, projected.crs, float(resolution))
    counts = {}
    with rasterio.open(
        output, "w", **profile, count=len(names), dtype="uint8", nodata=255
    ) as dst:
        for band, name in enumerate(names, 1):
            shapes = [
                (geometry, 1) for geometry in projected.loc[labels == name].geometry
            ]
            values = rasterize(
                shapes,
                out_shape=(profile["height"], profile["width"]),
                transform=profile["transform"],
                fill=0,
                all_touched=True,
                dtype="uint8",
            )
            dst.write(values, band)
            dst.set_band_description(band, name)
            counts[name] = int(np.count_nonzero(values))
        dst.update_tags(
            stisp_input_semantics=SEMANTICS,
            class_label_origin="category_field",
            category_field=category_field,
            source_feature_count=len(frame),
        )
    return {
        "sourceFeatures": len(frame),
        "classCount": len(names),
        "classes": names,
        "positivePixels": counts,
        "resolution": float(resolution),
        "allTouched": True,
        "width": profile["width"],
        "height": profile["height"],
    }


def binary_raster_masks(path, output, *, label="", class_labels=None):
    """Preserve declared band labels; categorical codes need an explicit legend."""
    class_labels = class_labels or {}
    with rasterio.open(path) as src:
        if src.crs is None:
            raise ValueError("栅格转换需要真实坐标系")
        if src.count > MAX_CLASSES or max(src.width, src.height) > MAX_EDGE:
            raise ValueError("输入栅格超过本次类别或网格资源边界")
        binary = True
        for _, window in src.block_windows(1):
            values = src.read(window=window, masked=True)
            if not np.isin(values.compressed(), [0, 1]).all():
                binary = False
                break
        if not binary and (src.count != 1 or not class_labels):
            raise ValueError("分类值不是0/1，请提供真实类别值到名称的class_labels映射")
        if binary:
            names = [
                class_label(
                    src.descriptions[i]
                    or (label if src.count == 1 else f"{label or '波段'}_{i + 1}")
                )
                for i in range(src.count)
            ]
        else:
            names = [class_label(name) for name in class_labels.values()]
        if len(set(names)) != len(names) or not 1 <= len(names) <= MAX_CLASSES:
            raise ValueError("输出类别名称重复、缺失或超出上限")
        profile = {
            **src.profile,
            "driver": "GTiff",
            "count": len(names),
            "dtype": "uint8",
            "nodata": 255,
            "compress": "DEFLATE",
        }
        with rasterio.open(output, "w", **profile) as dst:
            for band, name in enumerate(names, 1):
                dst.set_band_description(band, name)
            for _, window in src.block_windows(1):
                if binary:
                    values = (
                        src.read(window=window, masked=True).filled(255).astype("uint8")
                    )
                    dst.write(values, window=window)
                else:
                    raw = src.read(1, window=window, masked=True)
                    valid = ~np.ma.getmaskarray(raw)
                    unknown = set(raw.compressed().tolist()) - set(
                        float(key) for key in class_labels
                    )
                    if unknown:
                        raise ValueError(
                            "类别映射未覆盖实际值：" + str(sorted(unknown)[:10])
                        )
                    for band, code in enumerate(class_labels, 1):
                        dst.write(
                            np.where(
                                valid, (raw.data == float(code)).astype("uint8"), 255
                            ).astype("uint8"),
                            band,
                            window=window,
                        )
            dst.update_tags(
                stisp_input_semantics=SEMANTICS,
                class_label_origin="source_name"
                if binary and src.count == 1 and not src.descriptions[0]
                else "band_description"
                if binary
                else "explicit_class_labels",
            )
    return {"classCount": len(names), "classes": names, "binary": binary}


def combine_masks(
    entries,
    output,
    *,
    bounds,
    crs,
    resolution=None,
    cancelled=lambda: None,
    label_transform=lambda value: value,
):
    """Merge authorized masks on an explicit common grid, one band at a time."""
    with ExitStack() as stack:
        readers = []
        resolutions = []
        channels = {}
        for entry in entries:
            cancelled()
            src = stack.enter_context(rasterio.open(entry["path"]))
            if src.crs is None:
                raise ValueError("来源缺少坐标系")
            transform, _, _ = calculate_default_transform(
                src.crs, crs, src.width, src.height, *src.bounds
            )
            resolutions.append(abs(transform.a))
            readers.append(src)
            for band in range(1, src.count + 1):
                label = (
                    src.descriptions[band - 1]
                    if src.tags().get("stisp_input_semantics") == SEMANTICS
                    and not entry.get("forceLabel")
                    else entry.get("label")
                    if src.count == 1 and entry.get("label")
                    else src.descriptions[band - 1]
                )
                if not label:
                    raise ValueError("多波段分类栅格须声明每个波段的类别名称")
                channels.setdefault(class_label(label_transform(label)), []).append(
                    (src, band)
                )
        if len(channels) > MAX_CLASSES:
            raise ValueError(f"本次类别总数超过{MAX_CLASSES}类资源边界")
        chosen = float(resolution or min(resolutions, default=100))
        # Keep the first compatible native grid's origin so identical source
        # grids do not acquire a gratuitous half-pixel translation.
        west, south, east, north = bounds
        if readers and readers[0].crs == rasterio.crs.CRS.from_user_input(crs):
            x, y = readers[0].transform.c, readers[0].transform.f
            west = x + math.floor((west - x) / chosen) * chosen
            north = y + math.ceil((north - y) / chosen) * chosen
        profile = grid([west, south, east, north], crs, chosen)
        names = sorted(channels) or ["未提供类别资料"]
        with rasterio.open(
            output, "w", **profile, count=len(names), dtype="uint8", nodata=255
        ) as dst:
            for band, name in enumerate(names, 1):
                cancelled()
                result = np.full(
                    (profile["height"], profile["width"]), 255, dtype="uint8"
                )
                for src, index in channels.get(name, []):
                    temporary = np.full(result.shape, 255, dtype="uint8")
                    reproject(
                        rasterio.band(src, index),
                        temporary,
                        src_transform=src.transform,
                        src_crs=src.crs,
                        dst_transform=profile["transform"],
                        dst_crs=crs,
                        src_nodata=src.nodata,
                        dst_nodata=255,
                        resampling=Resampling.nearest,
                    )
                    valid = temporary != 255
                    if not np.isin(temporary[valid], [0, 1]).all():
                        raise ValueError("类别掩膜必须为0/1，不能静默重解释分类值")
                    both = valid & (result != 255)
                    result[both] = np.maximum(result[both], temporary[both])
                    result[valid & (result == 255)] = temporary[valid & (result == 255)]
                if not channels:
                    result.fill(0)
                dst.write(result, band)
                dst.set_band_description(band, name)
            dst.update_tags(
                stisp_input_semantics=SEMANTICS,
                stisp_empty_collection="0" if channels else "1",
            )
    return {
        "classCount": len(channels),
        "classes": sorted(channels),
        "resolution": chosen,
        "width": profile["width"],
        "height": profile["height"],
    }
