"""Hand-calculated rasters/areas and independent evidence-ranking checks."""
import csv
import json
from pathlib import Path
import runpy

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box
import yaml

from apps.compute.packages import validate_manifest
from apps.compute.quality import validate_report

ROOT = Path(__file__).resolve().parents[3] / 'examples/compute'
FIELDS = ['zone_id', 'date', 'event_type', 'land_use', 'evidence_id', 'source', 'confidence', 'value']
DATES = {'early_date': '2025-09-15', 'late_date': '2026-09-15'}


class Context:
    def __init__(self, directory, inputs, parameters=None):
        self.directory = directory
        self.inputs = inputs
        self.parameters = parameters or {}
        directory.mkdir(parents=True, exist_ok=True)

    def input_path(self, key):
        return self.inputs[key]

    def output_path(self, name):
        return self.directory / name


def raster(path, values, *, transform=None, crs=32645, tags=None):
    array = np.array(values, dtype='float32')
    if array.ndim == 2:
        array = array[None]
    _, height, width = array.shape
    with rasterio.open(path, 'w', driver='GTiff', width=width, height=height, count=len(array),
        dtype='float32', nodata=-9999, crs=crs, transform=transform or from_origin(0, height * 30, 30, 30)) as target:
        target.write(array)
        if tags:
            target.update_tags(**tags)
    return path


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def execute(name, context):
    before = {key: path.read_bytes() for key, path in context.inputs.items()}
    runpy.run_path(ROOT / name / 'main.py')['run'](context)
    assert all(path.read_bytes() == before[key] for key, path in context.inputs.items())
    report = json.loads(context.output_path('quality.json').read_text(encoding='utf-8'))
    validate_report(report)
    return report


def change_context(tmp_path, early, late, mask=None, **parameters):
    array = np.array(early)
    inputs = {
        'early_ndvi': raster(tmp_path / 'early.tif', early),
        'late_ndvi': raster(tmp_path / 'late.tif', late),
        'valid_mask': raster(tmp_path / 'mask.tif', np.ones(array.shape) if mask is None else mask),
    }
    return Context(tmp_path / 'change-output', inputs, {**DATES, **parameters})


def evidence(**overrides):
    return {'zone_id': 'right', 'date': DATES['late_date'], 'event_type': 'harvest', 'land_use': 'cropland',
        'evidence_id': 'survey-1', 'source': '模拟调查记录', 'confidence': 1, 'value': 1, **overrides}


def priority_context(tmp_path, values=None, observations=None, *, ids=None, geometry=None, tags=None, parameters=None):
    values = values if values is not None else [[-0.4, -0.2, -0.6, -0.6], [-0.4, 0.2, -0.6, -0.6]]
    source = raster(tmp_path / 'change.tif', values, tags=DATES if tags is None else tags)
    ids = ids or ['left', 'right']
    frame = gpd.GeoDataFrame({'zone_id': ids, 'retained': list(range(len(ids)))},
        geometry=geometry or [box(0, 0, 60, 60), box(60, 0, 120, 60)], crs=32645)
    vector = tmp_path / 'zones.gpkg'
    frame.to_file(vector, layer='data', driver='GPKG', index=False)
    table = tmp_path / 'context.csv'
    with table.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(observations or [])
    return Context(tmp_path / 'priority-output', {'change': source, 'zones': vector, 'context': table}, parameters)


def statistics(context):
    return {row['zone_id']: row for row in read_csv(context.output_path('zone-statistics.csv'))}


@pytest.mark.parametrize('name', ['ndvi-change-candidates', 'ecology-investigation-priority'])
def test_manifests_follow_platform_contract(name):
    spec = validate_manifest(yaml.safe_load((ROOT / name / 'operator.yaml').read_text(encoding='utf-8')))
    assert spec['qualityReport'] == {'file': 'quality.json'}
    assert spec['agent']['enabled']
    assert spec['deterministic']


def test_hand_calculated_ndvi_change_area_and_connected_candidates(tmp_path):
    context = change_context(tmp_path, [[0.8, 0.4], [0.6, 0.7]], [[0.3, 0.4], [0.9, 0.2]])
    quality = execute('ndvi-change-candidates', context)
    with rasterio.open(context.output_path('change.tif')) as result, rasterio.open(context.inputs['early_ndvi']) as original:
        np.testing.assert_allclose(result.read(1), [[-0.5, 0], [0.3, -0.5]], atol=1e-7)
        assert (result.crs, result.transform, result.shape) == (original.crs, original.transform, original.shape)
        assert result.nodata == -9999
        assert result.tags()['early_date'] == DATES['early_date']
    table = read_csv(context.output_path('statistics.csv'))[0]
    assert int(table['valid_pixels']) == 4
    assert float(table['valid_area_m2']) == 3600
    assert float(table['decline_area_m2']) == 1800
    assert float(table['mean_change']) == pytest.approx(-0.175, abs=1e-7)
    candidates = gpd.read_file(context.output_path('candidates.gpkg'))
    assert len(candidates) == 2
    assert candidates.area.sum() == pytest.approx(1800)
    assert candidates.pixel_count.sum() == 2
    assert quality['status'] == 'passed'


def test_common_two_band_mask_nodata_and_out_of_range_are_explicit(tmp_path):
    context = change_context(tmp_path, [[0.8, 0.4, -9999], [0.5, 1.2, 0.2]],
        [[0.4, 0.45, 0.6], [0.1, 0.3, -0.1]], mask=[[[1, 1, 1], [1, 1, 1]], [[1, 1, 1], [0, 1, 1]]])
    quality = execute('ndvi-change-candidates', context)
    with rasterio.open(context.output_path('change.tif')) as result:
        np.testing.assert_array_equal(result.read_masks(1), [[255, 255, 0], [0, 0, 255]])
    table = read_csv(context.output_path('statistics.csv'))[0]
    assert int(table['valid_pixels']) == 3
    assert float(table['valid_area_m2']) == 2700
    assert float(table['decline_area_m2']) == 1800
    assert quality['status'] == 'needs_review'
    assert quality['metrics']['outOfRangePixels'] == 1


def test_float32_threshold_boundary_is_consistent(tmp_path):
    context = change_context(tmp_path, [[0.7]], [[0.55]])
    execute('ndvi-change-candidates', context)
    assert read_csv(context.output_path('statistics.csv'))[0]['decline_pixels'] == '1'


@pytest.mark.parametrize('mode', ['stable', 'all_invalid'])
def test_empty_candidate_layer_and_all_invalid_quality(tmp_path, mode):
    context = change_context(tmp_path, [[0.5]], [[0.5]], mask=[[0 if mode == 'all_invalid' else 1]])
    report = execute('ndvi-change-candidates', context)
    assert gpd.read_file(context.output_path('candidates.gpkg')).empty
    assert report['status'] == ('needs_review' if mode == 'all_invalid' else 'passed')


@pytest.mark.parametrize('case', ['transform', 'size', 'crs', 'geographic', 'date_order', 'bad_date'])
def test_wrong_grid_dates_and_area_units_fail(tmp_path, case):
    context = change_context(tmp_path, [[0.5]], [[0.2]])
    if case == 'transform':
        raster(context.inputs['late_ndvi'], [[0.2]], transform=from_origin(1, 30, 30, 30))
    elif case == 'size':
        raster(context.inputs['late_ndvi'], [[0.2, 0.2]])
    elif case == 'crs':
        raster(context.inputs['late_ndvi'], [[0.2]], crs=32644)
    elif case == 'geographic':
        for key, value in [('early_ndvi', [[0.5]]), ('late_ndvi', [[0.2]]), ('valid_mask', [[1]])]:
            raster(context.inputs[key], value, crs=4326)
    elif case == 'date_order':
        context.parameters['late_date'] = context.parameters['early_date']
    else:
        context.parameters['early_date'] = '2025/09/15'
    with pytest.raises(ValueError):
        runpy.run_path(ROOT / 'ndvi-change-candidates/main.py')['run'](context)


def test_zone_statistics_hand_area_weighted_mean_and_base_order(tmp_path):
    context = priority_context(tmp_path)
    quality = execute('ecology-investigation-priority', context)
    rows = statistics(context)
    assert float(rows['left']['total_area_m2']) == 3600
    assert float(rows['left']['valid_area_m2']) == 3600
    assert float(rows['left']['mean_change']) == pytest.approx(-0.2, abs=1e-7)
    assert float(rows['left']['decline_area_m2']) == 2700
    assert float(rows['left']['decline_fraction']) == 0.75
    assert float(rows['left']['priority_score']) == pytest.approx(0.555, abs=1e-7)
    assert rows['right']['priority_rank'] == '1'
    assert rows['left']['priority_rank'] == '2'
    result = gpd.read_file(context.output_path('priority.gpkg'))
    original = gpd.read_file(context.inputs['zones'])
    assert result.geometry.equals(original.geometry)
    assert result.crs == original.crs
    assert result.retained.tolist() == [0, 1]
    assert quality['status'] == 'passed'


def test_low_coverage_is_separate_from_investigation_ranking(tmp_path):
    context = priority_context(tmp_path, [[-0.4, -9999, -0.6, -0.6], [-9999, -9999, -0.6, -0.6]])
    report = execute('ecology-investigation-priority', context)
    rows = statistics(context)
    assert float(rows['left']['valid_area_m2']) == 900
    assert float(rows['left']['coverage']) == 0.25
    assert rows['left']['priority_class'] == '优先补资料'
    assert rows['left']['priority_rank'] == ''
    assert rows['right']['priority_rank'] == '1'
    assert report['status'] == 'passed'
    assert report['metrics']['dataNeededZones'] == 1


def test_matching_harvest_evidence_changes_order_and_retains_explanation(tmp_path):
    context = priority_context(tmp_path, observations=[evidence()])
    report = execute('ecology-investigation-priority', context)
    rows = statistics(context)
    assert rows['left']['priority_rank'] == '1'
    assert rows['right']['priority_rank'] == '2'
    assert float(rows['right']['priority_score']) == pytest.approx(0.79 * 0.25, abs=1e-7)
    assert rows['right']['evidence_ids'] == 'survey-1'
    assert '收获解释' in rows['right']['reason']
    assert report['metrics']['matchedEvidenceCount'] == 1


@pytest.mark.parametrize('override', [{'date': '2024-09-15'}, {'date': '2027-09-15'}, {'date': ''},
    {'zone_id': 'unrelated'}, {'land_use': 'forest'}, {'confidence': 0.2}, {'source': ''}, {'value': 0}, {'value': 'nan'}, {'value': 'inf'}])
def test_unrelated_or_insufficient_evidence_does_not_change_order(tmp_path, override):
    context = priority_context(tmp_path, observations=[evidence(**override)])
    execute('ecology-investigation-priority', context)
    rows = statistics(context)
    assert rows['right']['priority_rank'] == '1'
    assert float(rows['right']['priority_score']) == pytest.approx(0.79, abs=1e-7)


def test_region_identifiers_do_not_select_an_answer(tmp_path):
    context = priority_context(tmp_path, ids=['陌生区域-17', '另一个区-93'], observations=[evidence(zone_id='另一个区-93')])
    execute('ecology-investigation-priority', context)
    rows = statistics(context)
    assert rows['陌生区域-17']['priority_rank'] == '1'
    assert float(rows['另一个区-93']['priority_score']) == pytest.approx(0.1975, abs=1e-7)


def test_harvest_does_not_erase_independent_drought_evidence(tmp_path):
    context = priority_context(tmp_path, observations=[evidence(),
        evidence(event_type='drought', evidence_id='drought-1', value=0.8, confidence=0.9),
        evidence(event_type='drought', evidence_id='drought-2', value=0.8, confidence=0.9)])
    execute('ecology-investigation-priority', context)
    row = statistics(context)['right']
    assert float(row['pressure_support']) == pytest.approx(0.72)
    assert float(row['priority_score']) == pytest.approx(0.79 * 0.25 + 0.15 * 0.72, abs=1e-7)


def test_partial_pixel_area_is_exact_and_outside_extent_reduces_coverage(tmp_path):
    context = priority_context(tmp_path, [[-0.4]], ids=['half', 'outside'], geometry=[box(0, 0, 15, 30), box(0, 0, 60, 30)])
    execute('ecology-investigation-priority', context)
    rows = statistics(context)
    assert float(rows['half']['total_area_m2']) == float(rows['half']['valid_area_m2']) == 450
    assert float(rows['half']['coverage']) == 1
    assert float(rows['half']['decline_area_m2']) == 450
    assert float(rows['outside']['total_area_m2']) == 1800
    assert float(rows['outside']['valid_area_m2']) == 900
    assert float(rows['outside']['coverage']) == 0.5
    assert rows['outside']['priority_class'] == '优先补资料'


def test_change_dates_can_be_explicit_but_cannot_conflict(tmp_path):
    context = priority_context(tmp_path, tags={}, parameters=DATES)
    execute('ecology-investigation-priority', context)
    with rasterio.open(context.inputs['change'], 'r+') as source:
        source.update_tags(**DATES)
    context.parameters = {**DATES, 'late_date': '2027-09-15'}
    with pytest.raises(ValueError, match='不一致'):
        runpy.run_path(ROOT / 'ecology-investigation-priority/main.py')['run'](context)
