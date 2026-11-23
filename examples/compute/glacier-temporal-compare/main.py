"""Compare class areas and pixel transitions in the shared area of two registered classifications."""

from contextlib import ExitStack
import csv
from datetime import date
import json

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT

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
    "no_prior": "未找到同样区、同任务的前一登记期分类。",
    "no_common_coverage": "检索到前期分类，但两期没有共同有效像元。",
    "matched": "已对比最近一次较早登记的分类；差值只统计共同覆盖且有效的区域。",
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


def assert_mask_contract(context, target, port, *, nodata=NODATA):
    tr = target.transform
    crs = target.crs.to_epsg() if target.crs else None
    if (
        target.driver != "GTiff"
        or target.count != 1
        or target.dtypes != ("uint8",)
        or target.nodata != nodata
        or not (crs is not None and (32601 <= crs <= 32660 or 32701 <= crs <= 32760))
        or (tr.a, tr.b, tr.d, tr.e) != (PIXEL_METRES, 0, 0, -PIXEL_METRES)
        or not np.isfinite(tuple(tr)).all()
        or target.width * target.height > MAX_PIXELS
    ):
        stop(
            context,
            "GLACIER_MASK_CONTRACT",
            "请选择已登记的3米UTM单波段分类图。图幅或缺测标记与该成果的登记类型不同。",
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
    code_only = context.parameters.get("baseline_basis") == "registered_codes"
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
            "前一登记期须早于本期。",
            ["current", "baseline"] if has_baseline else ["current"],
            "human_review",
        )
    if reason not in BASELINE_REASONS or has_baseline != (reason == "matched"):
        stop(
            context,
            "GLACIER_COMPARABILITY",
            "前期须是同样区、同任务的已登记分类图。",
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
            assert_mask_contract(
                context, baseline, "baseline", nodata=0 if code_only else NODATA
            )
            if code_only or (current.crs, current.transform, current.shape) != (
                baseline.crs,
                baseline.transform,
                baseline.shape,
            ):
                baseline = stack.enter_context(
                    WarpedVRT(
                        baseline,
                        crs=current.crs,
                        transform=current.transform,
                        width=current.width,
                        height=current.height,
                        nodata=NODATA,
                        src_nodata=baseline.nodata,
                        resampling=Resampling.nearest,
                        warp_mem_limit=64,
                    )
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
        stop(context, "GLACIER_NO_COVERAGE", "本期分类没有有效像元。", ["current"])
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
        if code_only and code == "ice":
            latest = previous = delta = None
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
                    "commonAreaKm2": round(common_pixels * PIXEL_KM2, 6)
                    if has_baseline
                    else None,
                    "changedPercent": round(
                        100
                        * (common_pixels - int(np.trace(transitions)))
                        / common_pixels,
                        8,
                    )
                    if has_baseline
                    else None,
                    "netClass1Km2": rows[1][7],
                    "netClass2Km2": rows[2][7],
                    "netIceAreaKm2": round(net * PIXEL_KM2, 6)
                    if net is not None and not code_only
                    else None,
                },
                "knowledgeFacts": {
                    "area": "原生UTM投影面积，不是坡表面积。",
                    "coverage": "前期按最近邻对齐到本期，只统计两期共同覆盖且有效的像元。",
                    "registration": "登记期是成果入账日期，不是卫星拍摄日期。",
                    "interpretation": (
                        "上一登记期是交接标准图：0为缺测，类别含义未核实；仅对比编码，不报告冰川净增减。"
                        if code_only
                        else "结果反映两次登记分类的差异。"
                    ),
                },
            },
            ensure_ascii=False,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
