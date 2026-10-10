"""Validate a complete evidence-backed attribute plan before writing a new map."""
import csv
import hashlib
import json
import math

import geopandas as gpd
from pyproj import CRS
from shapely.geometry import Point

EDITABLE = {'contact_type', 'lithology'}
CHANGE_FIELDS = ['feature_id', 'field', 'old_value', 'new_value', 'evidence_id', 'rule_id', 'reason', 'input_checksum']
RULE_FIELDS = {'rule_id', 'field', 'allowed_values', 'min_confidence', 'operation'}
SURVEY_FIELDS = {'feature_id', 'field', 'value', 'confidence', 'evidence_id', 'source', 'x', 'y', 'date'}


def map_checksum(frame):
    # Keep the canonical payload identical to geology-check/main.py.
    records = []
    for _, row in frame.iterrows():
        records.append({'feature_id': str(row.feature_id),
                        'geometry': row.geometry.normalize().wkb_hex,
                        **{field: str(row.get(field, '')) for field in sorted(EDITABLE)}})
    payload = {'crs': frame.crs.to_wkt(),
               'features': sorted(records, key=lambda row: row['feature_id'])}
    return hashlib.sha256(json.dumps(payload, sort_keys=True,
                                    ensure_ascii=False).encode()).hexdigest()


def _table(path, fields: set) -> list[dict]:
    with open(path, encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not fields <= set(reader.fieldnames or []):
            raise ValueError('表格缺少字段：' + ','.join(sorted(fields)))
        rows = []
        for row in reader:
            if len(rows) >= 10000 or None in row or any(row[key] is None for key in fields):
                raise ValueError('表格行格式错误或超过10000条')
            rows.append(row)
        return rows


def _rules(rows: list[dict]) -> dict:
    result = {}
    for row in rows:
        field, identity = row['field'], row['rule_id']
        try:
            confidence = float(row['min_confidence'])
        except ValueError as exc:
            raise ValueError('结构化规则置信度无效') from exc
        if (field not in EDITABLE or not identity.strip() or identity in result
                or row['operation'] != 'set_attribute'
                or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise ValueError('结构化规则字段、操作、置信度或编号无效')
        values = set(row['allowed_values'].split('|')) - {''}
        if not values:
            raise ValueError('规则需要明确列出允许的新值')
        result[identity] = {**row, 'values': values, 'minimum': confidence}
    return result


def _applies(survey: dict, feature, rule: dict, tolerance: float) -> bool:
    if str(survey['feature_id']) != str(feature.feature_id):
        return False
    if survey['field'] != rule['field'] or survey['value'] not in rule['values']:
        return False
    try:
        confidence = float(survey['confidence'])
        x, y = float(survey['x']), float(survey['y'])
    except ValueError:
        return False
    return (math.isfinite(confidence) and rule['minimum'] <= confidence <= 1
        and math.isfinite(x) and math.isfinite(y)
        and feature.geometry.distance(Point(x, y)) <= tolerance
        and bool(survey['source'].strip()) and bool(survey['evidence_id'].strip()))


def _validate_map(frame) -> None:
    if frame.empty or frame.crs is None or 'feature_id' not in frame:
        raise ValueError('地图需坐标系、稳定feature_id和至少一个要素')
    if frame.feature_id.isna().any() or frame.feature_id.astype(str).duplicated().any() or any(not str(v).strip() for v in frame.feature_id):
        raise ValueError('feature_id不可缺失、为空或重复')
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise ValueError('本次编辑不接受缺失或空几何')
    if any(geometry.geom_type not in {'Polygon', 'MultiPolygon'} for geometry in frame.geometry):
        raise ValueError('本次编辑接受面或多面地图')


def _to_working_frame(frame, parameters: dict):
    epsg = parameters.get('working_epsg', 32645)
    if type(epsg) is not int or not 1 <= epsg <= 999999:
        raise ValueError('工作投影EPSG须为有效整数')
    working = frame.to_crs(epsg=epsg)
    crs = CRS.from_user_input(working.crs)
    if not crs.is_projected or not crs.axis_info or any(abs(axis.unit_conversion_factor - 1) > 1e-9 for axis in crs.axis_info[:2]):
        raise ValueError('本次编辑需要米制投影地图，以明确空间容差')
    return working, epsg


def _plan(frame, changes: list[dict], rules: dict, surveys: list[dict], tolerance: float, checksum: str) -> list[dict]:
    features = {str(row.feature_id): (index, row) for index, row in frame.iterrows()}
    evidence = {row['evidence_id']: row for row in surveys}
    if len(evidence) != len(surveys) or any(not key.strip() for key in evidence):
        raise ValueError('调查证据编号不可缺失或重复')
    seen, accepted = set(), []
    for change in changes:
        identity, field = change['feature_id'], change['field']
        if identity not in features or field not in EDITABLE or field not in frame:
            raise ValueError('修改对象不存在或字段不在允许编辑范围')
        if (identity, field) in seen:
            raise ValueError('同一要素字段不可重复修改')
        seen.add((identity, field))
        if change['input_checksum'] != checksum:
            raise ValueError('输入地图校验和已变化，请基于当前版本重新检查和规划')
        index, feature = features[identity]
        if str(feature[field]) != change['old_value']:
            raise ValueError('修改表原值与当前地图不一致')
        if change['old_value'] == change['new_value']:
            raise ValueError('修改表新旧值相同，无需编辑')
        rule = rules.get(change['rule_id'])
        if rule is None or rule['field'] != field or change['new_value'] not in rule['values']:
            raise ValueError('修改规则不存在、字段不匹配或新值不在允许值中')
        survey = evidence.get(change['evidence_id'])
        if survey is None or survey['value'] != change['new_value'] or not _applies(survey, feature, rule, tolerance):
            raise ValueError('修改证据不存在或对象、位置、置信度、来源、新值不满足规则')
        supported = [row for row in surveys if _applies(row, feature, rule, tolerance)]
        if len({row['value'] for row in supported}) > 1:
            raise ValueError('同一对象有互相冲突的高置信调查记录，保留待复核')
        if not change['reason'].strip():
            raise ValueError('修改原因不可为空')
        accepted.append({**change, 'row_index': index, 'survey': survey})
    return accepted


def _csv(path, rows: list[dict], fields: list[str]) -> None:
    with open(path, 'w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run(context):
    original = gpd.read_file(context.input_path('features'))
    _validate_map(original)
    frame, working_epsg = _to_working_frame(original, context.parameters)
    raw = context.parameters.get('tolerance_m', 1)
    if type(raw) not in (float, int) or not math.isfinite(raw) or raw < 0:
        raise ValueError('空间容差须为非负有限数值')
    changes = _table(context.input_path('changes'), set(CHANGE_FIELDS))
    rules = _rules(_table(context.input_path('rules'), RULE_FIELDS))
    surveys = _table(context.input_path('surveys'), SURVEY_FIELDS)
    checksum = map_checksum(frame)
    accepted = _plan(frame, changes, rules, surveys, raw, checksum)
    # Every plan row is validated before any result file or feature is changed.
    result = original.copy()
    for item in accepted:
        result.at[item['row_index'], item['field']] = item['new_value']
    by_feature = {}
    for item in accepted:
        by_feature.setdefault(item['feature_id'], []).append(item)
    flat = {'change_fields': [], 'change_old': [], 'change_new': [], 'change_reason': [],
        'change_evidence': [], 'change_rule': [], 'check_status': []}
    for _, row in result.iterrows():
        items = by_feature.get(str(row.feature_id), [])
        flat['change_fields'].append(';'.join(item['field'] for item in items))
        flat['change_old'].append(';'.join(item['field'] + '=' + item['old_value'] for item in items))
        flat['change_new'].append(';'.join(item['field'] + '=' + item['new_value'] for item in items))
        for key, source in (('change_reason', 'reason'), ('change_evidence', 'evidence_id'), ('change_rule', 'rule_id')):
            flat[key].append(';'.join(item[source] for item in items))
        flat['check_status'].append('corrected' if items else 'unchanged')
    for key, values in flat.items():
        result[key] = values
    output_checksum = map_checksum(result.to_crs(epsg=working_epsg))
    log = []
    for item in accepted:
        survey = item['survey']
        log.append({**{key: item[key] for key in CHANGE_FIELDS}, 'status': 'applied',
            'verified_source': survey['source'], 'confidence': float(survey['confidence']),
            'survey_x': float(survey['x']), 'survey_y': float(survey['y']),
            'survey_date': survey['date'], 'output_checksum': output_checksum})
    result.to_file(context.output_path('corrected.gpkg'), layer='data', driver='GPKG', index=False)
    _csv(context.output_path('changes.csv'), log, CHANGE_FIELDS + ['status', 'verified_source', 'confidence', 'survey_x', 'survey_y', 'survey_date', 'output_checksum'])
    metrics = {'total_features': len(frame), 'change_count': len(log), 'modified_features': len(by_feature),
        'unchanged_features': len(frame) - len(by_feature), 'invalid_geometry': int((~result.geometry.is_valid).sum()),
        'input_checksum': checksum, 'output_checksum': output_checksum, 'reference_used': False,
        'evidence_verified': True, 'geometry_preserved': True, 'tolerance_m': raw, 'working_epsg': working_epsg}
    _csv(context.output_path('statistics.csv'), [metrics], list(metrics))
    report = {'version': 1, 'status': 'needs_review' if metrics['invalid_geometry'] else 'passed',
        'summary': f'按调查证据和结构化规则完成{len(log)}项属性修改；全部几何保留，原始输入保留，随后重跑填图检查复核。',
        'metrics': metrics, 'knowledgeFacts': {'geologyEdit': metrics}}
    with open(context.output_path('quality.json'), 'w', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, allow_nan=False)
    if hasattr(context, 'progress'):
        context.progress(100, '已完成受约束属性编辑，保留原图及逐项修改记录')
