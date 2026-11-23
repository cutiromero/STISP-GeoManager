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
EVIDENCE_FIELDS = (
    "current_date",
    "baseline_date",
    "current_source",
    "baseline_source",
    "comparable",
)
EVIDENCE_MAX_BYTES = 16_384


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


def read_observation_evidence(context, has_baseline):
    if "observations" not in context.inputs:
        if not has_baseline:
            return None, None
        stop(
            context,
            "GLACIER_COMPARABILITY",
            "双期比较必须绑定项目内已核对的观测依据表，不能推测时相或代为确认可比性。",
            ["baseline", "observations"],
            "human_review",
        )
    path = context.input_path("observations")
    rows = []
    if path.stat().st_size <= EVIDENCE_MAX_BYTES:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames or []
            if len(fields) == len(EVIDENCE_FIELDS) and set(fields) == set(
                EVIDENCE_FIELDS
            ):
                rows = list(reader)
    if (
        len(rows) != 1
        or set(rows[0]) != set(EVIDENCE_FIELDS)
        or any(not isinstance(value, str) for value in rows[0].values())
    ):
        stop(
            context,
            "GLACIER_EVIDENCE",
            "观测依据必须是含五个规定字段和一条记录的UTF-8 CSV。",
            ["observations"],
        )
    evidence = rows[0]
    current_day = exact_date(evidence["current_date"])
    baseline_day = exact_date(evidence["baseline_date"])
    if (
        not current_day
        or (has_baseline and (not baseline_day or baseline_day >= current_day))
        or (not has_baseline and evidence["baseline_date"])
    ):
        stop(
            context,
            "GLACIER_DATE_ORDER",
            "请填写有源数据依据的YYYY-MM-DD观测日；有基线时，基线日期必须早于新观测。",
            ["observations"],
            "human_review",
        )
    if (
        not evidence["current_source"].strip()
        or (
            has_baseline
            and (
                not evidence["baseline_source"].strip()
                or evidence["comparable"] != "yes"
            )
        )
        or (
            not has_baseline and (evidence["baseline_source"] or evidence["comparable"])
        )
    ):
        stop(
            context,
            "GLACIER_COMPARABILITY",
            "请提供日期依据；双期须人工核实同样区、传感器与季节可比、同模型同处理，并填写comparable=yes。",
            ["observations"],
            "human_review",
        )
    return current_day, baseline_day


def run(context):
    has_baseline = "baseline" in context.inputs
    current_day, baseline_day = read_observation_evidence(context, has_baseline)

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
        stop(
            context,
            "GLACIER_NO_OVERLAP",
            "两期没有共同有效覆盖，不生成变化值。",
            ["current", "baseline"],
        )
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
            )
        ],
    )
    net = rows[-1][6]
    context.output_path("quality.json").write_text(
        json.dumps(
            {
                "version": 1,
                "status": "passed",
                "summary": "共同有效区的时相差值，供对照复核。"
                if has_baseline
                else "第一期基线；无历史差值。",
                "metrics": {
                    "comparisonStatus": "compared" if has_baseline else "baseline_only",
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
