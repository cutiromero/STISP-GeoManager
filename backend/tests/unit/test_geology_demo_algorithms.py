"""Independent check/edit integration on survey facts, without reference maps."""
import csv
import json
from pathlib import Path
import runpy

import geopandas as gpd
import pytest
from shapely.geometry import Polygon, box
import yaml

from apps.compute.packages import validate_manifest
from apps.compute.quality import validate_report

ROOT = Path(__file__).resolve().parents[3] / 'examples/compute'
CHANGE_FIELDS = ['feature_id', 'field', 'old_value', 'new_value', 'evidence_id', 'rule_id', 'reason', 'input_checksum']
SURVEY_FIELDS = ['feature_id', 'field', 'value', 'confidence', 'evidence_id', 'source', 'x', 'y', 'date']
RULE_FIELDS = ['rule_id', 'field', 'allowed_values', 'min_confidence', 'operation']


class Context:
    def __init__(self, directory, inputs, parameters=None):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.inputs = inputs
        self.parameters = {'working_epsg': 32645, **(parameters or {})}
        self.progress_calls = []

    def input_path(self, key):
        return self.inputs[key]

    def output_path(self, name):
        return self.directory / name

    def progress(self, percent, text):
        self.progress_calls.append((percent, text))


def write_csv(path, rows, fields):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def load(name):
    return runpy.run_path(ROOT / name / 'main.py')


def rule(**overrides):
    return {'rule_id': 'contact-rule', 'field': 'contact_type', 'allowed_values': 'conformable|fault',
        'min_confidence': 0.8, 'operation': 'set_attribute', **overrides}


def survey(**overrides):
    return {'feature_id': 'unit-2', 'field': 'contact_type', 'value': 'fault', 'confidence': 0.95,
        'evidence_id': 'survey-2', 'source': '模拟调查记录', 'x': 500150, 'y': 4000050, 'date': '2026-09-15', **overrides}


def fixture(tmp_path, *, normalized=False, invalid=False, surveys=None):
    geometries = [box(500000, 4000000, 500100, 4000100), box(500100, 4000000, 500200, 4000100),
        box(500200, 4000000, 500300, 4000100)]
    if invalid:
        geometries[0] = Polygon([(500000, 4000000), (500100, 4000100), (500100, 4000000), (500000, 4000100)])
    frame = gpd.GeoDataFrame({'feature_id': ['unit-1', 'unit-2', 'unit-3'], 'contact_type': ['conformable'] * 3,
        'lithology': ['granite', 'limestone', 'basalt'], 'untouched': [11, 22, 33]}, geometry=geometries, crs=32645)
    if normalized:
        frame = frame.to_crs(4326)
    source = tmp_path / 'features.gpkg'
    frame.to_file(source, layer='data', driver='GPKG', index=False)
    survey_path, rules_path = tmp_path / 'surveys.csv', tmp_path / 'rules.csv'
    observations = surveys if surveys is not None else [survey(), survey(feature_id='unit-3', x=500250, confidence=0.3, evidence_id='uncertain-3')]
    write_csv(survey_path, observations, SURVEY_FIELDS)
    write_csv(rules_path, [rule()], RULE_FIELDS)
    return Context(tmp_path / 'check-output', {'features': source, 'surveys': survey_path, 'rules': rules_path})


def check(context):
    before = {key: path.read_bytes() for key, path in context.inputs.items()}
    load('geology-check')['run'](context)
    assert all(path.read_bytes() == before[key] for key, path in context.inputs.items())
    report = json.loads(context.output_path('quality.json').read_text(encoding='utf-8'))
    validate_report(report)
    return read_csv(context.output_path('issues.csv')), report


def edit_context(tmp_path, context, issues, *, changes=None):
    planned = [{key: row[key] for key in CHANGE_FIELDS} for row in issues
        if row['status'] == 'repairable' and row['field'] in {'contact_type', 'lithology'}]
    path = tmp_path / 'changes-input.csv'
    write_csv(path, planned if changes is None else changes, CHANGE_FIELDS)
    return Context(tmp_path / 'edit-output', {**context.inputs, 'changes': path})


def edit(context):
    before = {key: path.read_bytes() for key, path in context.inputs.items()}
    load('geology-edit')['run'](context)
    assert all(path.read_bytes() == before[key] for key, path in context.inputs.items())
    report = json.loads(context.output_path('quality.json').read_text(encoding='utf-8'))
    validate_report(report)
    return report


@pytest.mark.parametrize('name', ['geology-check', 'geology-edit'])
def test_manifest_contract(name):
    spec = validate_manifest(yaml.safe_load((ROOT / name / 'operator.yaml').read_text(encoding='utf-8')))
    assert spec['qualityReport'] == {'file': 'quality.json'}
    assert spec['agent']['enabled']


@pytest.mark.parametrize('normalized', [False, True])
def test_real_check_edit_recheck_preserves_correct_objects_and_geometry(tmp_path, normalized):
    context = fixture(tmp_path, normalized=normalized)
    issues, report = check(context)
    assert report['metrics']['total_features'] == 3
    assert report['metrics']['repairable'] == report['metrics']['needs_review'] == 1
    assert {row['feature_id'] for row in issues} == {'unit-2', 'unit-3'}
    planned = edit_context(tmp_path, context, issues)
    quality = edit(planned)
    original = gpd.read_file(context.inputs['features'])
    corrected = gpd.read_file(planned.output_path('corrected.gpkg'))
    assert corrected.crs == original.crs
    assert corrected.geometry.to_wkb().tolist() == original.geometry.to_wkb().tolist()
    assert corrected.untouched.tolist() == [11, 22, 33]
    assert corrected.lithology.tolist() == original.lithology.tolist()
    assert corrected.contact_type.tolist() == ['conformable', 'fault', 'conformable']
    assert corrected.check_status.tolist() == ['unchanged', 'corrected', 'unchanged']
    assert corrected.change_evidence.iloc[1] == 'survey-2'
    assert quality['status'] == 'passed'
    assert quality['metrics']['change_count'] == quality['metrics']['modified_features'] == 1
    assert quality['metrics']['unchanged_features'] == 2
    recheck = Context(tmp_path / 'recheck-output', {**context.inputs, 'features': planned.output_path('corrected.gpkg')})
    remaining, final = check(recheck)
    assert len(remaining) == 1 and remaining[0]['feature_id'] == 'unit-3'
    assert remaining[0]['status'] == 'needs_review'
    assert final['metrics']['repairable'] == 0


def test_checksum_identical_between_operators_and_independent_of_row_order(tmp_path):
    context = fixture(tmp_path)
    frame = gpd.read_file(context.inputs['features'])
    checksum = load('geology-check')['map_checksum'](frame)
    assert checksum == load('geology-edit')['map_checksum'](frame)
    assert checksum == load('geology-edit')['map_checksum'](frame.iloc[::-1])
    changed = frame.copy()
    changed.loc[0, 'lithology'] = 'new rock'
    assert checksum != load('geology-edit')['map_checksum'](changed)


@pytest.mark.parametrize('case', ['stale_checksum', 'false_evidence', 'duplicate', 'wrong_old', 'illegal_new',
    'illegal_field', 'wrong_rule', 'empty_reason', 'no_op', 'unknown_feature', 'wrong_projection'])
def test_invalid_edit_plan_rejected_before_any_result_file(tmp_path, case):
    context = fixture(tmp_path)
    issues, _ = check(context)
    changes = [{key: row[key] for key in CHANGE_FIELDS} for row in issues if row['status'] == 'repairable']
    item = changes[0]
    edits = {'stale_checksum': ('input_checksum', '0' * 64), 'false_evidence': ('evidence_id', 'not-real'),
        'wrong_old': ('old_value', 'fault'), 'illegal_new': ('new_value', 'intrusive'),
        'illegal_field': ('field', 'geometry'), 'wrong_rule': ('rule_id', 'not-real'),
        'empty_reason': ('reason', ''), 'no_op': ('new_value', 'conformable'), 'unknown_feature': ('feature_id', 'absent')}
    if case in edits:
        item[edits[case][0]] = edits[case][1]
    if case == 'duplicate':
        changes.append(dict(item))
    planned = edit_context(tmp_path, context, issues, changes=changes)
    if case == 'wrong_projection':
        planned.parameters['working_epsg'] = 32644
    before = context.inputs['features'].read_bytes()
    with pytest.raises(ValueError):
        load('geology-edit')['run'](planned)
    assert context.inputs['features'].read_bytes() == before
    assert not list(planned.directory.iterdir())


@pytest.mark.parametrize('override', [{'confidence': 0.2}, {'x': 999999}, {'source': ''},
    {'feature_id': 'unit-1'}, {'field': 'lithology'}, {'value': 'conformable'}, {'confidence': 'nan'}, {'x': 'inf'}])
def test_insufficient_or_mismatched_survey_cannot_modify_map(tmp_path, override):
    context = fixture(tmp_path)
    issues, _ = check(context)
    planned = edit_context(tmp_path, context, issues)
    write_csv(context.inputs['surveys'], [survey(**override)], SURVEY_FIELDS)
    with pytest.raises(ValueError, match='证据'):
        load('geology-edit')['run'](planned)
    assert not planned.output_path('corrected.gpkg').exists()


def test_conflicting_high_confidence_surveys_keep_object_for_review(tmp_path):
    observations = [survey(), survey(value='conformable', evidence_id='opposing-2')]
    context = fixture(tmp_path, surveys=observations)
    issues, _ = check(context)
    assert issues[0]['status'] == 'needs_review'
    assert '冲突' in issues[0]['reason']
    frame = gpd.read_file(context.inputs['features'])
    change = {'feature_id': 'unit-2', 'field': 'contact_type', 'old_value': 'conformable', 'new_value': 'fault',
        'evidence_id': 'survey-2', 'rule_id': 'contact-rule', 'reason': '计划',
        'input_checksum': load('geology-check')['map_checksum'](frame)}
    planned = edit_context(tmp_path, context, issues, changes=[change])
    with pytest.raises(ValueError, match='冲突'):
        load('geology-edit')['run'](planned)


def test_empty_plan_preserves_evidence_insufficient_objects(tmp_path):
    context = fixture(tmp_path, surveys=[survey(confidence=0.2)])
    issues, _ = check(context)
    assert issues[0]['status'] == 'needs_review'
    planned = edit_context(tmp_path, context, issues)
    report = edit(planned)
    original = gpd.read_file(context.inputs['features'])
    corrected = gpd.read_file(planned.output_path('corrected.gpkg'))
    assert corrected.contact_type.tolist() == original.contact_type.tolist()
    assert corrected.geometry.to_wkb().tolist() == original.geometry.to_wkb().tolist()
    assert report['metrics']['change_count'] == 0
    assert read_csv(planned.output_path('changes.csv')) == []


def test_check_detects_invalid_geometry_and_edit_preserves_it_for_review(tmp_path):
    context = fixture(tmp_path, invalid=True)
    issues, report = check(context)
    assert report['metrics']['invalid_geometry'] == 1
    assert any(row['field'] == 'geometry' and row['status'] == 'repairable' for row in issues)
    planned = edit_context(tmp_path, context, issues)
    quality = edit(planned)
    original = gpd.read_file(context.inputs['features'])
    corrected = gpd.read_file(planned.output_path('corrected.gpkg'))
    assert corrected.geometry.to_wkb().tolist() == original.geometry.to_wkb().tolist()
    assert quality['status'] == 'needs_review'


def test_check_reports_actual_overlap_area(tmp_path):
    context = fixture(tmp_path, surveys=[])
    frame = gpd.read_file(context.inputs['features'])
    frame.loc[1, 'geometry'] = box(500050, 4000000, 500150, 4000100)
    frame.to_file(context.inputs['features'], layer='data', driver='GPKG', index=False)
    issues, report = check(context)
    assert report['metrics']['overlap_pairs'] == 1
    assert '5000.000平方米' in issues[0]['reason']


def test_duplicate_survey_identity_is_rejected(tmp_path):
    context = fixture(tmp_path, surveys=[survey(), survey()])
    with pytest.raises(ValueError, match='重复'):
        load('geology-check')['run'](context)
    frame = gpd.read_file(context.inputs['features'])
    change = {'feature_id': 'unit-2', 'field': 'contact_type', 'old_value': 'conformable', 'new_value': 'fault',
        'evidence_id': 'survey-2', 'rule_id': 'contact-rule', 'reason': '计划',
        'input_checksum': load('geology-check')['map_checksum'](frame)}
    planned = edit_context(tmp_path, context, [], changes=[change])
    with pytest.raises(ValueError, match='重复'):
        load('geology-edit')['run'](planned)


def test_two_editable_fields_are_independently_verified_and_all_rows_are_atomic(tmp_path):
    context = fixture(tmp_path, surveys=[survey(), survey(field='lithology', value='sandstone', evidence_id='rock-2')])
    write_csv(context.inputs['rules'], [rule(), rule(rule_id='rock-rule', field='lithology', allowed_values='limestone|sandstone')], RULE_FIELDS)
    issues, _ = check(context)
    assert len(issues) == 2 and {row['field'] for row in issues} == {'contact_type', 'lithology'}
    planned = edit_context(tmp_path, context, issues)
    report = edit(planned)
    result = gpd.read_file(planned.output_path('corrected.gpkg'))
    assert result.contact_type.iloc[1] == 'fault'
    assert result.lithology.iloc[1] == 'sandstone'
    assert report['metrics']['change_count'] == 2
    assert report['metrics']['modified_features'] == 1
    assert 'rock-2' in result.change_evidence.iloc[1]
    changes = [{key: row[key] for key in CHANGE_FIELDS} for row in issues]
    changes[1]['evidence_id'] = 'false-evidence'
    fresh = Context(tmp_path / 'atomic-output', {**context.inputs, 'changes': tmp_path / 'bad-plan.csv'})
    write_csv(fresh.inputs['changes'], changes, CHANGE_FIELDS)
    with pytest.raises(ValueError, match='证据'):
        load('geology-edit')['run'](fresh)
    assert not list(fresh.directory.iterdir())
