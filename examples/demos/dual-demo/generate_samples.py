"""Reproducible synthetic dual-demo inputs, with separate acceptance-only truth."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely import make_valid
from shapely.geometry import Polygon, box

SEED = 20261010
EPSG = 32645
EARLY_DATE = '2025-09-15'
LATE_DATE = '2026-09-15'
CONTEXT_FIELDS = ['zone_id', 'date', 'event_type', 'land_use', 'evidence_id', 'source', 'confidence', 'value', 'nature', 'note']
SURVEY_FIELDS = ['feature_id', 'field', 'value', 'confidence', 'evidence_id', 'source', 'x', 'y', 'date', 'nature', 'note']
RULE_FIELDS = ['rule_id', 'field', 'allowed_values', 'min_confidence', 'operation', 'nature', 'note']


def _csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _raster(path: Path, values: np.ndarray, transform, *, tags: dict, descriptions: list[str]) -> None:
    with rasterio.open(path, 'w', driver='GTiff', width=values.shape[2], height=values.shape[1],
        count=len(values), dtype=str(values.dtype), nodata=-9999 if values.dtype.kind == 'f' else 0,
        crs=EPSG, transform=transform, compress='deflate') as target:
        target.write(values)
        target.update_tags(**tags)
        for index, description in enumerate(descriptions, start=1):
            target.set_band_description(index, description)


def _reflectance(ndvi: np.ndarray) -> np.ndarray:
    # A fixed reflectance sum of 0.8 gives physically bounded red/NIR values.
    return np.stack((0.4 * (1 - ndvi), 0.4 * (1 + ndvi))).astype('float32')


def ecology(output: Path, seed: int) -> dict:
    output.mkdir()
    rng = np.random.default_rng(seed)
    height = width = 128
    pixel_size = 30
    west, north = 500000, 4400000
    transform = from_origin(west, north, pixel_size, pixel_size)
    early = np.full((height, width), 0.65, dtype='float32')
    late = np.full_like(early, 0.64)
    decline = rng.permutation(64 * 64)[:3277]
    decline_block = late[:64, 64:]
    decline_block.flat[decline] = 0.35
    late[64:, :64] = 0.30
    late[64:, 64:] = 0.20
    masks = np.ones((2, height, width), dtype='uint8')
    missing_block = np.zeros((64, 64), dtype='uint8')
    missing_block.flat[rng.permutation(64 * 64)[:819]] = 1
    masks[1, 64:, :64] = missing_block
    shared = {'nature': 'synthetic', 'source': 'STISP reproducible synthetic research demo', 'seed': str(seed),
        'reflectance_scale': '1', 'reflectance_offset': '0', 'red_band': '1', 'nir_band': '2',
        'cloud_mask_nature': 'simulated valid mask; no cloud classifier run'}
    for name, values, observed in [('early.tif', early, EARLY_DATE), ('late.tif', late, LATE_DATE)]:
        _raster(output / name, _reflectance(values), transform, tags={**shared, 'date': observed,
            'units': 'unitless reflectance'}, descriptions=['red reflectance', 'near-infrared reflectance'])
    _raster(output / 'mask.tif', masks, transform, tags={'nature': 'synthetic', 'seed': str(seed),
        'early_date': EARLY_DATE, 'late_date': LATE_DATE, 'valid_value': '1', 'invalid_value': '0',
        'meaning': 'band1 early validity, band2 late validity; use intersection'}, descriptions=['early valid', 'late valid'])
    extent = 64 * pixel_size
    geometries = [box(west, north - extent, west + extent, north),
        box(west + extent, north - extent, west + 2 * extent, north),
        box(west, north - 2 * extent, west + extent, north - extent),
        box(west + extent, north - 2 * extent, west + 2 * extent, north - extent)]
    zones = gpd.GeoDataFrame({'zone_id': ['stable', 'decline', 'missing', 'cropland'],
        'zone_name': ['稳定模拟区', '植被下降模拟区', '有效资料不足模拟区', '农田模拟区'],
        'land_use': ['natural_vegetation', 'natural_vegetation', 'natural_vegetation', 'cropland'],
        'nature': ['synthetic'] * 4}, geometry=geometries, crs=EPSG)
    zones.to_file(output / 'zones.gpkg', layer='data', driver='GPKG', index=False)
    initial = [{
        'zone_id': row.zone_id, 'date': EARLY_DATE, 'event_type': 'background', 'land_use': row.land_use,
        'evidence_id': 'background-' + row.zone_id, 'source': '模拟资料/生态背景表', 'confidence': 1,
        'value': row.land_use, 'nature': 'synthetic', 'note': '演示背景设定，可用真实资料替换',
    } for _, row in zones.iterrows()]
    initial.append({'zone_id': 'decline', 'date': '2026-08-25', 'event_type': 'water_shortage',
        'land_use': 'natural_vegetation', 'evidence_id': 'survey-water-shortage', 'source': '模拟资料/期间水源观测记录',
        'confidence': 0.9, 'value': 1, 'nature': 'synthetic', 'note': 'value=1为本次模拟严重度，非原始物理单位'})
    updated = [*initial, {'zone_id': 'cropland', 'date': '2026-09-14', 'event_type': 'harvest',
        'land_use': 'cropland', 'evidence_id': 'survey-harvest-added', 'source': '模拟资料/新增农田收获记录',
        'confidence': 0.95, 'value': 1, 'nature': 'synthetic', 'note': '新增证据支持收获解释；日期处于两期比较区间'}]
    _csv(output / 'context-initial.csv', initial, CONTEXT_FIELDS)
    _csv(output / 'context-updated.csv', updated, CONTEXT_FIELDS)
    return {'directory': 'ecology', 'grid': {'width': width, 'height': height, 'epsg': EPSG,
        'pixelSizeM': pixel_size, 'transform': list(transform)[:6]}, 'seed': seed,
        'dates': {'early': EARLY_DATE, 'late': LATE_DATE}, 'bandRoles': {'1': 'red reflectance', '2': 'near-infrared reflectance'},
        'reflectanceScale': 1, 'reflectanceOffset': 0, 'roles': {
            'early_image': 'ecology/early.tif', 'late_image': 'ecology/late.tif', 'valid_mask': 'ecology/mask.tif',
            'zones': 'ecology/zones.gpkg', 'context_initial': 'ecology/context-initial.csv', 'context_updated': 'ecology/context-updated.csv'},
        'scenario': {'stable': {'earlyNdvi': 0.65, 'lateNdvi': 0.64},
            'decline': {'earlyNdvi': 0.65, 'lateNdviDeclining': 0.35, 'decliningPixels': 3277, 'totalPixels': 4096},
            'missing': {'earlyNdvi': 0.65, 'lateNdvi': 0.30, 'commonValidPixels': 819, 'totalPixels': 4096},
            'cropland': {'earlyNdvi': 0.65, 'lateNdvi': 0.20, 'decliningPixels': 4096}},
        'contextUpdate': {'addedEvidenceIds': ['survey-harvest-added'], 'initialEvidenceIncludes': ['survey-water-shortage']},
        'ruleNature': '可配置模拟排序规则；阈值、权重与置信度用于研究展示',
        'interpretation': '两期NDVI变化线索与调查优先区；模拟收获解释可改变排查顺序'}


def geology(output: Path, acceptance: Path) -> dict:
    output.mkdir()
    acceptance.mkdir()
    west, south = 510000, 4395000
    geometries = []
    for row in range(2):
        for col in range(3):
            x, y = west + col * 140, south + row * 140
            geometries.append(box(x, y, x + 100, y + 100))
    x, y = west + 140, south + 140
    geometries[4] = Polygon([(x, y), (x + 100, y), (x + 100, y + 100),
        (x + 50, y + 100), (x + 50, y + 120), (x + 50, y + 100), (x, y + 100)])
    assert not geometries[4].is_valid
    ids = [f'F{i:02}' for i in range(1, 7)]
    original = gpd.GeoDataFrame({'feature_id': ids, 'contact_type': ['整合'] * 6,
        'lithology': ['花岗岩', '砂岩', '石灰岩', '玄武岩', '页岩', '砂岩'],
        'map_note': ['模拟初始填图；依据资料逐项检查'] * 6, 'nature': ['synthetic'] * 6},
        geometry=geometries, crs=EPSG)
    original.to_file(output / 'initial.gpkg', layer='data', driver='GPKG', index=False)
    surveys = []
    for feature_id, confidence, evidence_id, note in [('F06', 0.95, 'survey-contact-F06', '明确调查记录，支持接触类型修改'),
        ('F04', 0.35, 'survey-uncertain-F04', '置信不足的异值记录，保留原图并等待核实')]:
        point = original.loc[original.feature_id == feature_id].geometry.iloc[0].representative_point()
        surveys.append({'feature_id': feature_id, 'field': 'contact_type', 'value': '断层', 'confidence': confidence,
            'evidence_id': evidence_id, 'source': '模拟资料/地质接触调查记录', 'x': point.x, 'y': point.y,
            'date': '2026-09-15', 'nature': 'synthetic', 'note': note})
    _csv(output / 'surveys.csv', surveys, SURVEY_FIELDS)
    _csv(output / 'rules.csv', [{'rule_id': 'survey-contact-consistency', 'field': 'contact_type',
        'allowed_values': '整合|断层', 'min_confidence': 0.8, 'operation': 'set_attribute', 'nature': 'synthetic',
        'note': '演示调查资料一致性规则；由编号、投影位置、明确调查值和置信度共同核验'}], RULE_FIELDS)
    reference = original.copy()
    repaired = make_valid(geometries[4])
    polygon = next(part for part in repaired.geoms if part.geom_type in {'Polygon', 'MultiPolygon'})
    reference.at[4, 'geometry'] = polygon
    reference.at[5, 'contact_type'] = '断层'
    reference.to_file(acceptance / 'geology-reference.gpkg', layer='reference', driver='GPKG', index=False)
    errors = [{'feature_id': 'F05', 'field': 'geometry', 'initial_value': 'invalid polygon with retraced spike',
        'reference_value': 'valid polygon; spike retained in repair audit', 'expected_action': 'geometry_repair_and_review',
        'scenario': 'seeded_error', 'description': '真实无效尖刺面；make_valid产生面与线片段，需保留审核说明'},
        {'feature_id': 'F06', 'field': 'contact_type', 'initial_value': '整合', 'reference_value': '断层',
            'expected_action': 'set_attribute', 'scenario': 'seeded_error', 'description': '同对象高置信模拟调查明确支持断层接触'},
        {'feature_id': 'F04', 'field': 'contact_type', 'initial_value': '整合', 'reference_value': '整合',
            'expected_action': 'preserve_and_review', 'scenario': 'insufficient_evidence', 'description': '低置信异值观测不构成确定设错，保留原值待核实'}]
    _csv(acceptance / 'geology-errors.csv', errors, list(errors[0]))
    return {'directory': 'geology', 'epsg': EPSG, 'workingEpsg': EPSG, 'featureCount': 6,
        'roles': {'initial_map': 'geology/initial.gpkg', 'surveys': 'geology/surveys.csv', 'rules': 'geology/rules.csv'},
        'ruleNature': '模拟调查资料一致性规则；有限属性操作和几何有效性用于展示',
        'acceptanceOnly': {'referenceMap': 'acceptance-isolated/geology-reference.gpkg',
            'scenarioList': 'acceptance-isolated/geology-errors.csv', 'excludedFromModelAndAlgorithms': True},
        'scenarioCounts': {'correctAttributes': 5, 'correctFeatures': 4, 'invalidGeometry': 1,
            'confirmedAttributeError': 1, 'uncertainObservationOnCorrectFeature': 1},
        'interpretation': '6面中4面内容正确（含一个低置信疑难观测），另有1个无效几何与1个明确接触错误'}


def generate(target: Path, seed: int = SEED) -> dict:
    target = target.resolve()
    target.mkdir(parents=True, exist_ok=True)
    expected = [target / name for name in ('ecology', 'geology', 'acceptance-isolated', 'manifest.json')]
    if any(path.exists() for path in expected):
        raise ValueError('此目录已有样例；请保留现有资料并选择新的输出目录')
    eco = ecology(target / 'ecology', seed)
    geo = geology(target / 'geology', target / 'acceptance-isolated')
    hashes = {}
    for path in sorted(target.rglob('*')):
        if path.is_file():
            with path.open('rb') as stream:
                hashes[path.relative_to(target).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
    manifest = {'schemaVersion': 1, 'nature': 'synthetic', 'seed': seed,
        'createdAt': datetime.now(timezone.utc).isoformat(),
        'source': 'STISP固定种子合成研究展示资料；影像与调查记录均为模拟',
        'ecology': eco, 'geology': geo, 'fileSha256': hashes,
        'storage': {'inputDirectories': ['ecology', 'geology'], 'acceptanceDirectory': 'acceptance-isolated',
            'acceptanceImportAllowed': False},
        'simulationStatement': '资料用于重复演示平台数据、算法、知识与模型联动。阈值和规则性质见各算法README。参考图及设错清单仅供独立验收。'}
    (target / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description='生成生态与地质模拟Demo输入（不写数据库）')
    parser.add_argument('output', type=Path, help='科研数据目录下的新样例目录')
    parser.add_argument('--seed', type=int, default=SEED)
    args = parser.parse_args()
    manifest = generate(args.output, args.seed)
    print(json.dumps({'output': str(args.output.resolve()), 'nature': 'synthetic',
        'seed': manifest['seed'], 'files': list(manifest['fileSha256'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
