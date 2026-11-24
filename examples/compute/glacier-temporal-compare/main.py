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
MAX_PIXELS = {3: 36_000_000, 10: 121_000_000}
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


def assert_mask_contract(context, target, port, pixel_metres, *, nodata=NODATA):
    tr = target.transform
    crs = target.crs.to_epsg() if target.crs else None
    if (
        target.driver not in {"GTiff", "VRT"}
        or target.count != 1
        or target.dtypes != ("uint8",)
        or target.nodata != nodata
        or not (crs is not None and (32601 <= crs <= 32660 or 32701 <= crs <= 32760))
        or (tr.a, tr.b, tr.d, tr.e) != (pixel_metres, 0, 0, -pixel_metres)
        or not np.isfinite(tuple(tr)).all()
        or target.width * target.height > MAX_PIXELS.get(pixel_metres, 0)
    ):
        stop(
            context,
            "GLACIER_MASK_CONTRACT",
            "请选择分辨率为3米或10米的已登记UTM分类，核对网格和缺测标记。",
            [port],
        )


def aligned_baseline(stack, target, current, *, nodata):
    return stack.enter_context(
        WarpedVRT(
            target,
            crs=current.crs,
            transform=current.transform,
            width=current.width,
            height=current.height,
            nodata=nodata,
            src_nodata=target.nodata,
            resampling=Resampling.nearest,
            warp_mem_limit=64,
        )
    )


def read_codes(context, target, port, window, class_count, *, coverage=None):
    values = target.read(1, window=window)
    valid = (values != NODATA) & (target.read_masks(1, window=window) != 0)
    if coverage is not None:
        valid &= coverage.dataset_mask(window=window) != 0
    if np.any(values[valid] >= class_count):
        stop(
            context,
            "GLACIER_CLASS_CODE",
            f"有效区只能使用0至{class_count - 1}的类别码。",
            [port],
        )
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
        metres = current.transform.a
        assert_mask_contract(context, current, "current", metres)
        binary = metres == 10
        labels = ("非冰川", "冰川") if binary else LABELS
        class_count = len(labels)
        pixel_km2 = metres**2 / 1_000_000
        baseline = None
        baseline_image = None
        if "baseline_image" in context.inputs:
            if not (binary and has_baseline and not code_only):
                stop(
                    context,
                    "GLACIER_COMPARABILITY",
                    "前期原图仅用于玛纳斯标准分类的有效范围。",
                    ["baseline_image"],
                )
            baseline_image = stack.enter_context(
                rasterio.open(context.input_path("baseline_image"))
            )
        if has_baseline:
            baseline = stack.enter_context(
                rasterio.open(context.input_path("baseline"))
            )
            assert_mask_contract(
                context,
                baseline,
                "baseline",
                metres,
                nodata=None
                if baseline_image is not None
                else 0
                if code_only
                else NODATA,
            )
            current_grid = (current.crs, current.transform, current.shape)
            baseline_grid = (baseline.crs, baseline.transform, baseline.shape)
            if binary and code_only:
                stop(
                    context,
                    "GLACIER_COMPARABILITY",
                    "玛纳斯交接二分类须使用原图有效掩膜。",
                    ["baseline"],
                )
            if baseline_image is not None and (
                (baseline_image.crs, baseline_image.transform, baseline_image.shape)
                != baseline_grid
                or baseline_image.count != 4
                or baseline_image.dtypes != ("uint8",) * 4
                or baseline_image.nodata != 0
            ):
                stop(
                    context,
                    "GLACIER_COMPARABILITY",
                    "前期原图与标准分类的网格或缺测标记不一致。",
                    ["baseline_image"],
                )
            if code_only or current_grid != baseline_grid:
                baseline = aligned_baseline(stack, baseline, current, nodata=NODATA)
                if baseline_image is not None:
                    baseline_image = aligned_baseline(
                        stack, baseline_image, current, nodata=0
                    )
        transitions = np.zeros((class_count, class_count), dtype=np.int64)
        current_counts = np.zeros(class_count, dtype=np.int64)
        earlier_valid = 0
        for _, window in current.block_windows(1):
            values, valid = read_codes(context, current, "current", window, class_count)
            current_counts += np.bincount(values[valid], minlength=class_count)
            if baseline is not None:
                prev, prev_valid = read_codes(
                    context,
                    baseline,
                    "baseline",
                    window,
                    class_count,
                    coverage=baseline_image,
                )
                earlier_valid += int(np.count_nonzero(prev_valid))
                common = valid & prev_valid
                pair_codes = prev[common] * class_count + values[common]
                transitions += np.bincount(
                    pair_codes, minlength=class_count**2
                ).reshape(transitions.shape)

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
    aggregate = [(str(code), label, [code]) for code, label in enumerate(labels)] + [
        ("ice", "冰川合计", list(range(1, class_count)))
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
                round(full * pixel_km2, 6),
                latest,
                previous,
                delta,
                round(delta * pixel_km2, 6) if delta is not None else None,
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
                round(int(transitions[old, new]) * pixel_km2, 6),
            )
            for old in range(class_count)
            for new in range(class_count)
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
                    "commonAreaKm2": round(common_pixels * pixel_km2, 6)
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
                    "netClass2Km2": None if binary else rows[2][7],
                    "netIceAreaKm2": round(net * pixel_km2, 6)
                    if net is not None and not code_only
                    else None,
                },
                "knowledgeFacts": {
                    "area": "原生UTM投影面积，不是坡表面积。",
                    "coverage": (
                        "交接标准图按配对原始影像的有效掩膜统计；0是有效非冰川。"
                        if baseline_image is not None
                        else "变化只统计两期有效像元的交集。"
                    ),
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
