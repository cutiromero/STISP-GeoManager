"""Native historical observations: physical values, display classes and real series."""

import csv
import json

# CONFIGURATION
COLORS = {
    0: (0, 0, 0, 0),
    1: (255, 225, 156, 255),
    2: (251, 165, 87, 255),
    3: (228, 91, 69, 255),
    4: (166, 47, 57, 255),
    255: (0, 0, 0, 0),
}
AREA_THRESHOLDS = [0, 100, 1000, 10000]
FRP_THRESHOLDS = [0, 0.001, 0.01, 0.1]


def run(context):
    import numpy as np
    import rasterio
    from operator_sdk import fail

    with rasterio.open(context.input_path("cube")) as source:
        raw = source.tags().get("stisp_cube_slice")
        if (
            not raw
            or source.tags().get("stisp_input_semantics")
            != "temporal_observation_stack_v1"
        ):
            fail(
                context,
                "WILDFIRE_INPUT_INVALID",
                "请选择已登记原生立方体及真实观测时期",
                remedy="replace_data",
                inputs=["cube"],
            )
        info = json.loads(raw)
        if source.count != len(info["series"]) or source.crs.to_epsg() != 4326:
            fail(
                context,
                "WILDFIRE_INPUT_INVALID",
                "时间切片栈的网格或序列不一致",
                remedy="replace_data",
                inputs=["cube"],
            )
        values = source.read(source.count, masked=True).filled(np.nan).astype("float32")
        finite = np.isfinite(values)
        positive = finite & (values > 0)
        if not finite.any():
            fail(
                context,
                "WILDFIRE_PERIOD_UNAVAILABLE",
                "所选区域与时期没有有效观测",
                remedy="adjust_parameters",
                parameters=["time_index", "west", "south", "east", "north"],
            )
        profile = {**source.profile, "count": 1, "nodata": -9999, "compress": "deflate"}
        with rasterio.open(
            context.output_path("observation.tif"), "w", **profile
        ) as output:
            output.write(np.where(finite, values, -9999), 1)
        classes = np.zeros(values.shape, dtype="uint8")
        classes[~finite] = 255
        thresholds = AREA_THRESHOLDS if info["unit"] == "ha" else FRP_THRESHOLDS
        legend = [{"code": 0, "name": "零观测值", "rgba": list(COLORS[0])}]
        for index, lower in enumerate(thresholds, 1):
            classes[finite & (values > lower)] = index
            label = (
                (
                    f"{lower:g}–{thresholds[index]:g}"
                    if index < len(thresholds)
                    else f"超过{lower:g}"
                )
                + " "
                + info["unit"]
            )
            legend.append({"code": index, "name": label, "rgba": list(COLORS[index])})
        legend.append({"code": 255, "name": "缺测", "rgba": list(COLORS[255])})
        with rasterio.open(
            context.output_path("classification.tif"),
            "w",
            **{**profile, "dtype": "uint8", "nodata": 255},
        ) as output:
            output.write_colormap(1, COLORS)
            output.write(classes, 1)
            output.update_tags(
                stisp_categorical=json.dumps(
                    {
                        "schemaVersion": 1,
                        "legend": legend,
                        "transparentValues": [0, 255],
                    },
                    ensure_ascii=False,
                )
            )
        total = float(values[finite].sum(dtype=np.float64))
        mean = float(values[finite].mean(dtype=np.float64))
        statistics = {
            "burned_area_ha": total if info["unit"] == "ha" else None,
            "frp_w_m2": mean if info["unit"] != "ha" else None,
            "valid_coverage_percent": float(finite.sum() / finite.size * 100),
        }
        facts = {
            **info,
            "statistics": statistics,
            "activeCells": int(positive.sum()),
            "validCells": int(finite.sum()),
            "gridCells": int(finite.size),
            "legend": legend,
            "sourceResourceId": context.inputs["cube"]["resourceId"],
            "inputSha256": context.inputs["cube"]["sha256"],
        }
        for file, rows in [
            ("statistics.csv", [statistics]),
            ("series.csv", info["series"]),
        ]:
            with context.output_path(file).open(
                "w", encoding="utf-8-sig", newline=""
            ) as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        context.output_path("quality.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "status": "passed",
                    "summary": "真实时间、产品有效掩膜、物理单位及格网检查通过。",
                    "metrics": statistics,
                    "knowledgeFacts": {"wildfireObservation": facts},
                },
                ensure_ascii=False,
            )
        )
        context.output_path("result.json").write_text(
            json.dumps(facts, ensure_ascii=False, indent=2)
        )
