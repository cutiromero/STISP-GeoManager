"""A non-geological adapter: raster observations to a band statistics table."""

import csv
import json
import math

import numpy as np
import rasterio


def run(context):
    rows = []
    with rasterio.open(context.input_path("source")) as source:
        selected = context.parameters.get("band", 0)
        bands = [selected] if selected else list(range(1, source.count + 1))
        if any(not 1 <= band <= source.count for band in bands):
            raise ValueError("波段不属于实际栅格")
        for band in bands:
            count = 0
            minimum = maximum = None
            sums = []
            for _, window in source.block_windows(band):
                values = (
                    source.read(band, window=window, masked=True)
                    .compressed()
                    .astype("float64")
                )
                if not np.isfinite(values).all():
                    raise ValueError("有效像元包含非有限值，无法可靠统计")
                if not len(values):
                    continue
                count += len(values)
                sums.append(float(values.sum(dtype="float64")))
                low, high = float(values.min()), float(values.max())
                minimum = low if minimum is None else min(minimum, low)
                maximum = high if maximum is None else max(maximum, high)
            rows.append(
                {
                    "band": band,
                    "name": source.descriptions[band - 1] or str(band),
                    "count": count,
                    "min": minimum,
                    "max": maximum,
                    "mean": math.fsum(sums) / count if count else None,
                }
            )
    with open(
        context.output_path("statistics.csv"), "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["band", "name", "count", "min", "max", "mean"]
        )
        writer.writeheader()
        writer.writerows(rows)
    report = {
        "version": 1,
        "status": "passed",
        "summary": "已按实际有效像元输出波段统计，原始像元未修改。",
        "metrics": {
            "bandRows": len(rows),
            "validPixels": sum(row["count"] for row in rows),
        },
        "knowledgeFacts": {
            "semantics": "raster_band_statistics_v1",
            "countScope": "all_valid_pixels",
        },
    }
    with open(context.output_path("quality.json"), "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False)
