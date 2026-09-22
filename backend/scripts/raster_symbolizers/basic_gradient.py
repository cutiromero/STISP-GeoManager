#!/usr/bin/env python
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling


PALETTES = {
    "poplar": np.array(
        [[24, 80, 71], [104, 148, 84], [232, 186, 94]], dtype=np.float32
    ),
    "water": np.array(
        [[34, 84, 120], [66, 145, 166], [184, 218, 214]], dtype=np.float32
    ),
    "thermal": np.array(
        [[35, 52, 76], [196, 92, 70], [246, 205, 112]], dtype=np.float32
    ),
}


def main() -> int:
    started = time.perf_counter()
    try:
        payload = json.loads(sys.stdin.read())
        raster_path = Path(payload["raster_path"])
        output_png_path = Path(payload["output_png_path"])
        rules = payload.get("rules") or {}
        size = payload["size"]
        width = int(size["width"])
        height = int(size["height"])
        palette = PALETTES.get(str(rules.get("palette", "poplar")), PALETTES["poplar"])

        with rasterio.open(raster_path) as src:
            data = src.read(
                1,
                out_shape=(height, width),
                masked=True,
                resampling=Resampling.bilinear,
            )

        image = colorize(data, palette, float(rules.get("opacity", 0.86)))
        output_png_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(image, mode="RGBA").save(output_png_path)
        result = {
            "status": "ok",
            "output_png_path": str(output_png_path),
            "width": width,
            "height": height,
            "stats": stats(data),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1


def colorize(data, palette: np.ndarray, opacity: float) -> np.ndarray:
    masked = np.ma.masked_invalid(data)
    valid = ~np.ma.getmaskarray(masked)
    output = np.zeros((*masked.shape, 4), dtype=np.uint8)
    if not np.any(valid):
        return output

    values = masked.filled(np.nan).astype(np.float32)
    minimum = np.nanmin(values)
    maximum = np.nanmax(values)
    if maximum == minimum:
        scaled = np.zeros_like(values, dtype=np.float32)
    else:
        scaled = np.clip((values - minimum) / (maximum - minimum), 0, 1)

    stops = np.array([0.0, 0.5, 1.0], dtype=np.float32)
    for channel in range(3):
        output[..., channel] = np.interp(scaled, stops, palette[:, channel]).astype(
            np.uint8
        )
    output[..., 3] = np.where(valid, int(np.clip(opacity, 0, 1) * 255), 0).astype(
        np.uint8
    )
    return output


def stats(data) -> dict:
    masked = np.ma.masked_invalid(data)
    if masked.count() == 0:
        return {"min": None, "max": None}
    return {"min": float(masked.min()), "max": float(masked.max())}


if __name__ == "__main__":
    raise SystemExit(main())
