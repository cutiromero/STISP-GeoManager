from __future__ import annotations

from typing import Any

import numpy as np

from apps.raster.services.constants import PALETTES


def hex_to_rgba(value: str) -> tuple[int, int, int, int]:
    text = value.strip().lstrip("#")
    if len(text) == 6:
        text = f"{text}ff"
    if len(text) != 8:
        return 0, 0, 0, 255
    return tuple(int(text[index : index + 2], 16) for index in range(0, 8, 2))  # type: ignore[return-value]


def palette_array(name: str) -> np.ndarray:
    colors = PALETTES.get(name, PALETTES["poplar"])
    return np.array([hex_to_rgba(color)[:3] for color in colors], dtype=np.float32)


def scale_array(
    values: np.ndarray, rules: dict[str, Any], metadata: dict[str, Any], band_index: int
) -> np.ndarray:
    from apps.raster.services.rules_engine import stretch_min_max

    if not rules.get("stretch", {}).get("enabled", True):
        return np.clip(values, 0, 255).astype(np.uint8)
    minimum, maximum = stretch_min_max(rules, metadata, band_index)
    scaled = (values - minimum) / (maximum - minimum)
    return np.clip(scaled * 255.0, 0, 255).astype(np.uint8)


def array_to_rgba(
    data: np.ma.MaskedArray, rules: dict[str, Any], metadata: dict[str, Any]
) -> np.ndarray:
    from apps.raster.services.rules_engine import output_source_bands

    mode = rules["mode"]
    masks = np.ma.getmaskarray(data)
    if masks.ndim == 0:
        valid = np.ones(data.shape[-2:], dtype=bool)
    else:
        valid = ~np.any(masks, axis=0)
    values = np.ma.filled(data, 0).astype(np.float32)
    output = np.zeros((values.shape[-2], values.shape[-1], 4), dtype=np.uint8)

    if mode == "rgb":
        if (
            rules.get("nodata", {}).get("enabled", True)
            and values.shape[0] == 3
        ):
            valid &= ~np.all(values[:3] == 0, axis=0)
        for index, band_index in enumerate(output_source_bands(rules)[:3]):
            output[..., index] = scale_array(values[index], rules, metadata, band_index)
        if values.shape[0] > 3:
            output[..., 3] = np.where(valid, np.clip(values[3], 0, 255), 0).astype(
                np.uint8
            )
        else:
            output[..., 3] = np.where(valid, 255, 0).astype(np.uint8)
        return output

    if mode == "gray":
        gray = scale_array(values[0], rules, metadata, output_source_bands(rules)[0])
        output[..., 0] = gray
        output[..., 1] = gray
        output[..., 2] = gray
        output[..., 3] = np.where(valid, 255, 0).astype(np.uint8)
        return output

    if mode == "unique":
        integer_values = values[0].astype(np.int64)
        for item in rules["uniqueValues"]:
            output[integer_values == int(item["value"])] = hex_to_rgba(
                str(item["color"])
            )
        output[..., 3] = np.where(valid, output[..., 3], 0).astype(np.uint8)
        return output

    scaled = (
        scale_array(values[0], rules, metadata, output_source_bands(rules)[0]).astype(
            np.float32
        )
        / 255.0
    )
    palette = palette_array(str(rules.get("palette") or "poplar"))
    stops = np.linspace(0.0, 1.0, len(palette), dtype=np.float32)
    for channel in range(3):
        output[..., channel] = np.interp(scaled, stops, palette[:, channel]).astype(
            np.uint8
        )
    output[..., 3] = np.where(valid, 255, 0).astype(np.uint8)
    return output
