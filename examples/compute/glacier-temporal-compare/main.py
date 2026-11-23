"""Compare class areas and pixel transitions on an already matched UTM grid."""

from contextlib import ExitStack
import csv
from datetime import date
import json

import numpy as np
import rasterio

from operator_sdk import fail

# Configuration: stable classes and deterministic calculation policy.
LABELS = ("背景", "洁净冰川", "表碛冰川")
NODATA = 255
PIXEL_METRES = 3
MAX_PIXELS = 36_000_000
PIXEL_KM2 = PIXEL_METRES**2 / 1_000_000
BASELINE_REASONS = {
    "no_current_date": "本期原始影像未登记可核实的观测日，不能确定前后顺序。",
    "no_series": "本期影像未登记观测系列，无法核实同样区的历史资料。",
    "no_prior": "项目内没有通过同系列、同格网、同模型及日期筛选的前期分类。",
    "no_common_coverage": "检索到前期分类，但两期没有共同有效像元。",
    "matched": "自动检索到时间最近的可比前期分类，差值仅统计共同有效像元。",
}


def stop(context, code, detail, ports, remedy="replace_data"):
    fail(context, code, detail, inputs=ports, remedy=remedy)


def exact_date(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def assert_mask_contract(context, target, port):
    tr = target.transform
    crs = target.crs.to_epsg() if target.crs else None
    if (
        target.driver != "GTiff"
        or target.count != 1
        or target.dtypes != ("uint8",)
        or target.nodata != NODATA
        or not (crs is not None and (32601 <= crs <= 32660 or 32701 <= crs <= 32760))
        or (tr.a, tr.b, tr.d, tr.e) != (PIXEL_METRES, 0, 0, -PIXEL_METRES)
        or not np.isfinite(tuple(tr)).all()
        or target.width * target.height > MAX_PIXELS
    ):
        stop(
            context,
            "GLACIER_MASK_CONTRACT",
            "请选择同法生成的3米北向上UTM单波段UInt8分类，0为有效背景、255为NoData；单幅最多3600万像元。",
            [port],
        )


def read_codes(context, target, port, window):
    values = target.read(1, window=window)
    valid = (values != NODATA) & (target.read_masks(1, window=window) != 0)
    if np.any(values[valid] > 2):
        stop(context, "GLACIER_CLASS_CODE", "有效区中出现0、1、2以外的类别码。", [port])
    return values, valid


def csv_rows(context, name, header, rows):
    with context.output_path(name).open("w", newline="", encoding="utf-8-sig") as out:
        writer = csv.writer(out)
        writer.writerow(header)
        writer.writerows(rows)


def run(context):
    has_baseline = "baseline" in context.inputs
    current_value = context.parameters.get("current_date", "")
    baseline_value = context.parameters.get("baseline_date", "")
    current_day = exact_date(current_value)
    baseline_day = exact_date(baseline_value)
    reason = context.parameters.get("baseline_reason", "no_prior")
    if (
        (current_value and not current_day)
        or (
            has_baseline
            and (not current_day or not baseline_day or baseline_day >= current_day)
        )
        or (not has_baseline and baseline_value)
    ):
        stop(
            context,
            "GLACIER_DATE_ORDER",
            "双期观测日必须有据可查，前期必须早于本期。",
            ["current", "baseline"] if has_baseline else ["current"],
            "human_review",
        )
    if reason not in BASELINE_REASONS or has_baseline != (reason == "matched"):
        stop(
            context,
            "GLACIER_COMPARABILITY",
            "前期影像必须通过同系列、同格网、同规约及真实日期核验。",
            ["current", "baseline"] if has_baseline else ["current"],
            "human_review",
        )

    with ExitStack() as stack:
        current = stack.enter_context(rasterio.open(context.input_path("current")))
        assert_mask_contract(context, current, "current")
        baseline = None
        if has_baseline:
            baseline = stack.enter_context(
                rasterio.open(context.input_path("baseline"))
            )
            assert_mask_contract(context, baseline, "baseline")
            if (current.crs, current.transform, current.shape) != (
                baseline.crs,
                baseline.transform,
                baseline.shape,
            ):
                stop(
                    context,
                    "GLACIER_GRID_MISMATCH",
                    "两期的原生坐标系、尺寸或仿射参数不同，不能直接比较；不自动重采样。",
                    ["current", "baseline"],
                )
        transitions = np.zeros((3, 3), dtype=np.int64)
        current_counts = np.zeros(3, dtype=np.int64)
        earlier_valid = 0
        for _, window in current.block_windows(1):
            values, valid = read_codes(context, current, "current", window)
            current_counts += np.bincount(values[valid], minlength=3)
            if baseline is not None:
                prev, prev_valid = read_codes(context, baseline, "baseline", window)
                earlier_valid += int(np.count_nonzero(prev_valid))
                common = valid & prev_valid
                pair_codes = prev[common] * 3 + values[common]
                transitions += np.bincount(pair_codes, minlength=9).reshape((3, 3))

        coverage = int(current_counts.sum())
        common_pixels = int(transitions.sum())
        total = current.width * current.height
        crs = current.crs.to_string()
    if coverage == 0:
        stop(context, "GLACIER_NO_COVERAGE", "新一期不存在有效观测像元。", ["current"])
    if has_baseline and not common_pixels:
        has_baseline = False
        reason = "no_common_coverage"
    # Rows use a consistent common mask only in a real comparison.
    comparable_now = transitions.sum(axis=0)
    comparable_prev = transitions.sum(axis=1)
    aggregate = [
        ("0", LABELS[0], [0]),
        ("1", LABELS[1], [1]),
        ("2", LABELS[2], [2]),
        ("ice", "冰川合计", [1, 2]),
    ]
    rows = []
    for code, label, indexes in aggregate:
        full = int(current_counts[indexes].sum())
        latest = int(comparable_now[indexes].sum()) if has_baseline else None
        previous = int(comparable_prev[indexes].sum()) if has_baseline else None
        delta = latest - previous if has_baseline else None
        rows.append(
            (
                code,
                label,
                full,
                round(full * PIXEL_KM2, 6),
                latest,
                previous,
                delta,
                round(delta * PIXEL_KM2, 6) if delta is not None else None,
            )
        )
    csv_rows(
        context,
        "glacier_areas.csv",
        (
            "class_code",
            "label",
            "current_valid_pixels",
            "current_area_km2",
            "common_current_pixels",
            "common_baseline_pixels",
            "common_net_pixels",
            "common_net_km2",
        ),
        rows,
    )
    interval = (
        (baseline_day.isoformat(), current_day.isoformat()) if has_baseline else ()
    )
    csv_rows(
        context,
        "glacier_transitions.csv",
        ("baseline_date", "current_date", "from_code", "to_code", "pixels", "area_km2"),
        (
            (
                *interval,
                old,
                new,
                int(transitions[old, new]),
                round(int(transitions[old, new]) * PIXEL_KM2, 6),
            )
            for old in range(3)
            for new in range(3)
        )
        if has_baseline
        else (),
    )
    csv_rows(
        context,
        "observation_coverage.csv",
        (
            "status",
            "current_date",
            "baseline_date",
            "native_crs",
            "scene_pixels",
            "current_valid_pixels",
            "baseline_valid_pixels",
            "common_valid_pixels",
            "common_valid_pct",
            "baseline_reason",
        ),
        [
            (
                "compared" if has_baseline else "baseline_only",
                current_day.isoformat() if current_day else None,
                baseline_day.isoformat() if has_baseline else None,
                crs,
                total,
                coverage,
                earlier_valid if has_baseline else None,
                common_pixels if has_baseline else None,
                round(100 * common_pixels / total, 8) if has_baseline else None,
                reason,
            )
        ],
    )
    net = rows[-1][6]
    context.output_path("quality.json").write_text(
        json.dumps(
            {
                "version": 1,
                "status": "passed",
                "summary": BASELINE_REASONS[reason],
                "metrics": {
                    "comparisonStatus": "compared" if has_baseline else "baseline_only",
                    "baselineReason": reason,
                    "currentDate": current_day.isoformat() if current_day else None,
                    "baselineDate": baseline_day.isoformat() if has_baseline else None,
                    "commonValidPixels": common_pixels if has_baseline else None,
                    "netIceAreaKm2": round(net * PIXEL_KM2, 6)
                    if net is not None
                    else None,
                },
                "knowledgeFacts": {
                    "area": "原生UTM投影面积，不是坡表面积。",
                    "coverage": "0是有效背景；255和无效掩膜排除。双期差值由共同有效区域的逐像元转换得到。",
                    "interpretation": "模型分类差异不自动代表物理冰川退缩、质量变化或预警。需对照日期、数据条件和季节雪等影响。",
                },
            },
            ensure_ascii=False,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
