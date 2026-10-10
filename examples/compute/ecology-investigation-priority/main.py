"""Area-weighted zone statistics and explicit evidence-conditioned demo ranking."""
import csv
from datetime import date
import hashlib
import json
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import CRS
import rasterio
from rasterio.features import geometry_mask
from shapely import area, intersection, polygons

CONTEXT_FIELDS = {'zone_id', 'date', 'event_type', 'land_use', 'evidence_id', 'source', 'confidence', 'value'}
DEFAULTS = {'min_coverage': 0.65, 'decline_threshold': -0.15, 'decline_weight': 0.7,
    'mean_weight': 0.3, 'context_weight': 0.15, 'harvest_discount': 0.75, 'min_confidence': 0.7}


def _hash(path) -> str:
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _parameters(parameters: dict) -> dict:
    result = {key: parameters.get(key, default) for key, default in DEFAULTS.items()}
    for key, value in result.items():
        if type(value) not in (float, int) or not math.isfinite(value):
            raise ValueError(f'{key}须为有限数字')
        low, high = (-2, 0) if key == 'decline_threshold' else (0, 1)
        if not low <= value <= high or (key == 'decline_threshold' and value == 0):
            raise ValueError(f'{key}超出允许范围')
    if result['decline_weight'] + result['mean_weight'] <= 0:
        raise ValueError('下降占比与平均下降的权重不能同时为0')
    return result


def _period(source, parameters: dict) -> tuple[date, date]:
    tags = source.tags()
    values = []
    for key in ('early_date', 'late_date'):
        supplied, tagged = parameters.get(key, ''), tags.get(key, '')
        if supplied and tagged and supplied != tagged:
            raise ValueError('观测时段参数与变化栅格日期标签不一致')
        value = supplied or tagged
        try:
            if not isinstance(value, str) or len(value) != 10:
                raise ValueError
            values.append(date.fromisoformat(value))
        except ValueError as exc:
            raise ValueError('变化栅格需要两期ISO日期标签或明确的日期参数') from exc
    if values[0] >= values[1]:
        raise ValueError('后期日期必须晚于前期日期')
    return tuple(values)


def _context(path) -> list[dict]:
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not CONTEXT_FIELDS <= set(reader.fieldnames or []):
            raise ValueError('背景/观测CSV缺少约定字段：' + ','.join(sorted(CONTEXT_FIELDS)))
        result, identifiers = [], set()
        for raw in reader:
            if len(result) >= 10000 or None in raw or any(raw[key] is None for key in CONTEXT_FIELDS):
                raise ValueError('背景/观测CSV行格式错误或超过10000行')
            row = {key: value.strip() for key, value in raw.items()}
            try:
                confidence = float(row['confidence']) if row['confidence'] else 0.0
            except ValueError as exc:
                raise ValueError('证据confidence须为[0,1]数字') from exc
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError('证据confidence须为[0,1]数字')
            key = (row['zone_id'], row['evidence_id'])
            if row['evidence_id'] and key in identifiers:
                raise ValueError('同一分区的evidence_id须唯一')
            identifiers.add(key)
            row['confidence_value'] = confidence
            try:
                row['observed_date'] = date.fromisoformat(row['date']) if len(row['date']) == 10 else None
            except ValueError:
                row['observed_date'] = None
            result.append(row)
    return result


def _pixel_weights(geometry, shape, transform) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Intersect actual pixel quadrilaterals, retaining partial boundary areas."""
    selected = geometry_mask([geometry], out_shape=shape, transform=transform, invert=True, all_touched=True)
    rows, cols = np.where(selected)
    if not rows.size:
        return rows, cols, np.empty(0, dtype='float64')
    dx, dy = np.array([0, 1, 1, 0]), np.array([0, 0, 1, 1])
    x, y = cols[:, None] + dx, rows[:, None] + dy
    corners = np.stack((transform.a * x + transform.b * y + transform.c,
        transform.d * x + transform.e * y + transform.f), axis=-1)
    weights = area(intersection(polygons(corners), geometry))
    positive = weights > 0
    return rows[positive], cols[positive], weights[positive]


def _evidence(records: list[dict], zone_id: str, early: date, late: date, options: dict) -> tuple[list[dict], int]:
    related = [row for row in records if row['zone_id'] == zone_id]
    accepted = [row for row in related if row['observed_date'] is not None
        and early <= row['observed_date'] <= late and row['confidence_value'] >= options['min_confidence']
        and row['source'] and row['evidence_id']]
    return accepted, len(related) - len(accepted)


def _severity(row: dict) -> float:
    try:
        value = float(row['value'])
    except ValueError:
        return 0.0
    return value if math.isfinite(value) and 0 <= value <= 1 else 0.0


def _harvest(row: dict) -> bool:
    if row['event_type'].casefold() != 'harvest' or row['land_use'].casefold() != 'cropland':
        return False
    value = row['value'].casefold()
    if value in {'false', 'no', '未发生', '未收获'}:
        return False
    try:
        number = float(value)
        return math.isfinite(number) and number > 0
    except ValueError:
        return True


def _score(row: dict, evidence: list[dict], options: dict) -> None:
    amplitude = max(0.0, -row['mean_change']) / 2 if row['mean_change'] is not None else 0.0
    normalizer = options['decline_weight'] + options['mean_weight']
    base = (options['decline_weight'] * row['decline_fraction'] + options['mean_weight'] * amplitude) / normalizer
    pressure_rows = [item for item in evidence if item['event_type'].casefold() in {'drought', 'water_shortage'}]
    pressure = max((_severity(item) * item['confidence_value'] for item in pressure_rows), default=0.0)
    harvest_rows = [item for item in evidence if _harvest(item)]
    harvest = max((item['confidence_value'] for item in harvest_rows), default=0.0)
    score = base * (1 - options['harvest_discount'] * harvest) + options['context_weight'] * pressure
    row.update(base_score=float(base), pressure_support=float(pressure), harvest_support=float(harvest),
        priority_score=float(score), evidence_ids=';'.join(item['evidence_id'] for item in evidence),
        evidence_sources=';'.join(item['evidence_id'] + ':' + item['source'] for item in evidence))
    reason = f"有效覆盖{row['coverage']:.1%}；下降占共同有效面积{row['decline_fraction']:.1%}"
    if row['mean_change'] is not None:
        reason += f"，平均NDVI变化{row['mean_change']:.4f}"
    if pressure:
        reason += '；匹配到同分区同期间的可信干旱/缺水线索，按演示权重增加调查分'
    if harvest:
        reason += '；匹配到同分区同期间的农田收获证据，支持收获解释并降低调查分'
    if not harvest and any(item['event_type'].casefold() == 'harvest' for item in evidence):
        reason += '；收获记录未满足农田/发生条件，保留核实'
    if not evidence:
        reason += '；暂无同分区同期间的可信观测，先按实际变化统计排序'
    if row['coverage'] < options['min_coverage']:
        reason += '；覆盖不足，优先补资料，当前不参加调查排名'
    row['reason'] = reason


def run(context):
    options = _parameters(context.parameters)
    paths = {key: context.input_path(key) for key in ('change', 'zones', 'context')}
    observations = _context(paths['context'])
    zones = gpd.read_file(paths['zones'])
    if zones.crs is None or zones.empty or 'zone_id' not in zones:
        raise ValueError('调查分区需有CRS、非空面要素与zone_id字段')
    if zones['zone_id'].isna().any():
        raise ValueError('zone_id不可为空')
    identifiers = [str(value).strip() for value in zones['zone_id']]
    if not all(identifiers) or len(identifiers) != len(set(identifiers)):
        raise ValueError('zone_id须为唯一的非空值')
    if any(geom is None or geom.is_empty or not geom.is_valid or geom.geom_type not in {'Polygon', 'MultiPolygon'} for geom in zones.geometry):
        raise ValueError('调查分区须为有效面或多面几何')
    records = []
    matched, ignored = 0, 0
    with rasterio.open(paths['change']) as source:
        if source.crs is None or source.count != 1:
            raise ValueError('变化栅格需为有CRS的单波段')
        crs = CRS.from_user_input(source.crs)
        if not crs.is_projected or not crs.axis_info or any(not math.isclose(axis.unit_conversion_factor, 1.0) for axis in crs.axis_info[:2]):
            raise ValueError('面积统计需要米制投影坐标系')
        determinant = abs(source.transform.a * source.transform.e - source.transform.b * source.transform.d)
        if not math.isfinite(determinant) or determinant <= 0:
            raise ValueError('变化栅格网格变换无效')
        early, late = _period(source, context.parameters)
        data = source.read(1, masked=True)
        measured = ~np.ma.getmaskarray(data) & np.isfinite(data.data)
        in_range = (data.data >= -2) & (data.data <= 2)
        valid = measured & in_range
        out_of_range = int(np.count_nonzero(measured & ~in_range))
        projected = zones.to_crs(source.crs)
        for zone_id, geometry in zip(identifiers, projected.geometry):
            total_area = float(geometry.area)
            if not math.isfinite(total_area) or total_area <= 0:
                raise ValueError('调查分区面积无效')
            rows, cols, weights = _pixel_weights(geometry, data.shape, source.transform)
            usable = valid[rows, cols]
            weights, values = weights[usable], data.data[rows[usable], cols[usable]]
            valid_area = float(weights.sum())
            declined = values <= options['decline_threshold'] + 1e-7
            decline_area = float(weights[declined].sum())
            coverage = min(1.0, valid_area / total_area)
            row = {'zone_id': zone_id, 'total_area_m2': total_area, 'valid_area_m2': valid_area,
                'coverage': coverage, 'mean_change': float(np.dot(values, weights) / valid_area) if valid_area else None,
                'decline_area_m2': decline_area, 'decline_fraction': decline_area / valid_area if valid_area else 0.0,
                'priority_class': '调查排序' if coverage >= options['min_coverage'] and valid_area else '优先补资料',
                'priority_rank': None, 'early_date': early.isoformat(), 'late_date': late.isoformat()}
            evidence, missed = _evidence(observations, zone_id, early, late, options)
            matched += len(evidence)
            ignored += missed
            _score(row, evidence, options)
            row['ignored_evidence_count'] = missed
            if not valid_area:
                row['reason'] = '分区内没有共同有效像元；优先补资料，当前不参加调查排名'
            records.append(row)
    known = set(identifiers)
    ignored += sum(row['zone_id'] not in known for row in observations)
    ranked = sorted((row for row in records if row['priority_class'] == '调查排序'), key=lambda row: -row['priority_score'])
    for rank, row in enumerate(ranked, start=1):
        row['priority_rank'] = rank
    with Path(context.output_path('zone-statistics.csv')).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    output = zones.copy()
    output['zone_id'] = identifiers
    for key in records[0]:
        if key != 'zone_id':
            output[key] = [row[key] for row in records]
    output['priority_rank'] = pd.array([row['priority_rank'] for row in records], dtype='Int64')
    output.to_file(context.output_path('priority.gpkg'), layer='priority', driver='GPKG', index=False)
    quality = {'version': 1, 'status': 'needs_review' if out_of_range else 'passed',
        'summary': f'已计算{len(records)}个分区；{len(ranked)}个进入调查排序，{len(records) - len(ranked)}个优先补资料。排序分数按明示演示规则计算。',
        'metrics': {'zoneCount': len(records), 'rankedZones': len(ranked), 'dataNeededZones': len(records) - len(ranked),
            'matchedEvidenceCount': matched, 'ignoredEvidenceCount': ignored, 'outOfRangePixels': out_of_range, 'parameters': options},
        'knowledgeFacts': {'ecologyInvestigation': {'earlyDate': early.isoformat(), 'lateDate': late.isoformat(),
            'coverageGateApplied': True, 'matchedByZoneAndPeriod': True, 'sourceSha256': {key: _hash(path) for key, path in paths.items()},
            'statisticsSha256': _hash(context.output_path('zone-statistics.csv')),
            'interpretation': '计算质量通过表示统计与明示排序规则执行正确；调查分数表达排查顺序，原因和长期生态状态结合进一步资料'}}}
    Path(context.output_path('quality.json')).write_text(json.dumps(quality, ensure_ascii=False, allow_nan=False), encoding='utf-8')
