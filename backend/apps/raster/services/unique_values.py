from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from apps.core.storage import StoragePathError, raster_processed_path
from apps.raster.models import RasterDataset
from apps.raster.services.categorical import (
    categorical_class_entries,
    default_categorical_color,
)
from apps.raster.services.exceptions import RasterRenderError
from apps.raster.services.rules_engine import is_integer_band

MAX_UNIQUE_VALUES = 4096


def classify_unique_values(dataset: RasterDataset, band_index: int) -> dict[str, Any]:
    if dataset.status != RasterDataset.Status.READY:
        raise RasterRenderError("栅格数据集尚未完成预处理")
    if band_index < 1 or band_index > max(1, dataset.band_count):
        raise RasterRenderError("波段编号超出范围")
    if not is_integer_band(dataset.processed_gdalinfo, band_index):
        raise RasterRenderError("唯一值分类仅支持整型波段，浮点型波段不适用")

    try:
        raster_path = raster_processed_path(dataset.processed_relative_path)
    except StoragePathError as exc:
        raise RasterRenderError(str(exc)) from exc
    if not Path(raster_path).exists():
        raise RasterRenderError(
            f"预处理栅格文件不存在：{dataset.processed_relative_path}"
        )

    import rasterio

    values: set[int] = set()
    with rasterio.open(raster_path) as src:
        dtype = np.dtype(src.dtypes[band_index - 1])
        if not np.issubdtype(dtype, np.integer):
            raise RasterRenderError("唯一值分类仅支持整型波段，浮点型波段不适用")
        for _, window in src.block_windows(band_index):
            block = src.read(band_index, window=window, masked=True)
            if np.ma.is_masked(block):
                data = block.compressed()
            else:
                data = np.asarray(block).ravel()
            if data.size == 0:
                continue
            values.update(int(value) for value in np.unique(data))
            if len(values) > MAX_UNIQUE_VALUES:
                raise RasterRenderError(
                    f"唯一值超过 {MAX_UNIQUE_VALUES} 个，不适合使用唯一值分类"
                )

    declared_classes = {
        int(item["value"]): item
        for item in categorical_class_entries(dataset.source_gdalinfo)
    }
    items = []
    for index, value in enumerate(sorted(values)):
        declared = declared_classes.get(value) or {}
        label = str(declared.get("label") or value)
        items.append(
            {
                "value": value,
                "label": label,
                "color": str(
                    declared.get("color")
                    or default_categorical_color(value, label, index)
                ),
            }
        )
    return {"band": band_index, "items": items}
