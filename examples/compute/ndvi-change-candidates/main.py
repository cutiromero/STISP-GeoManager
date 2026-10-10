"""Two-date NDVI change on a verified common grid; no network or database writes."""
import csv
from datetime import date
import hashlib
import json
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
from pyproj import CRS
import rasterio
from rasterio.features import geometry_mask, shapes
from shapely.geometry import shape

NODATA = -9999.0


def _dates(parameters: dict) -> tuple[date, date]:
    try:
        values = [parameters[key] for key in ('early_date', 'late_date')]
        if any(not isinstance(value, str) or len(value) != 10 for value in values):
            raise ValueError
        early, late = [date.fromisoformat(value) for value in values]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError('两期日期须为 YYYY-MM-DD 格式') from exc
    if early >= late:
        raise ValueError('后期日期必须晚于前期日期')
    return early, late


def _metre_area(source) -> float:
    if source.crs is None:
        raise ValueError('输入需要已知的米制投影坐标系')
    crs = CRS.from_user_input(source.crs)
    if not crs.is_projected or not crs.axis_info or any(
        not math.isclose(axis.unit_conversion_factor, 1.0) for axis in crs.axis_info[:2]
    ):
        raise ValueError('面积统计需要米制投影坐标系')
    transform = source.transform
    area = abs(transform.a * transform.e - transform.b * transform.d)
    if not math.isfinite(area) or area <= 0:
        raise ValueError('栅格网格变换无效')
    return area


def _same_grid(reference, source) -> None:
    if (reference.crs, reference.transform, reference.width, reference.height) != (
        source.crs, source.transform, source.width, source.height
    ):
        raise ValueError('两期NDVI与有效掩膜必须有相同CRS、网格变换和尺寸')


def _hash(path) -> str:
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _write_csv(path, records: list[dict]) -> None:
    with Path(path).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def run(context):
    early_date, late_date = _dates(context.parameters)
    threshold = context.parameters.get('decline_threshold', -0.15)
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or not -2 <= threshold < 0:
        raise ValueError('下降阈值须为[-2,0)内的有限数字')
    paths = {key: context.input_path(key) for key in ('early_ndvi', 'late_ndvi', 'valid_mask')}
    with rasterio.open(paths['early_ndvi']) as early, rasterio.open(paths['late_ndvi']) as late, rasterio.open(paths['valid_mask']) as mask:
        _same_grid(early, late)
        _same_grid(early, mask)
        pixel_area = _metre_area(early)
        if early.count != 1 or late.count != 1:
            raise ValueError('前期与后期NDVI须为单波段，采用[-1,1]尺度')
        if mask.count not in (1, 2):
            raise ValueError('有效掩膜须为1个共同有效波段或2个分期有效波段')
        first, second = early.read(1, masked=True), late.read(1, masked=True)
        masks = mask.read(masked=True)
        mask_valid = np.all(~np.ma.getmaskarray(masks) & np.isfinite(masks.data) & (masks.data > 0), axis=0)
        measured = ~np.ma.getmaskarray(first) & ~np.ma.getmaskarray(second) & np.isfinite(first.data) & np.isfinite(second.data)
        in_range = (first.data >= -1) & (first.data <= 1) & (second.data >= -1) & (second.data <= 1)
        out_of_range = int(np.count_nonzero(mask_valid & measured & ~in_range))
        valid = mask_valid & measured & in_range
        change = np.full(first.shape, NODATA, dtype='float32')
        change[valid] = second.data[valid].astype('float64') - first.data[valid].astype('float64')
        declined = valid & (change <= threshold + 1e-7)
        profile = early.profile.copy()
        profile.update(driver='GTiff', count=1, dtype='float32', nodata=NODATA)
        with rasterio.open(context.output_path('change.tif'), 'w', **profile) as output:
            output.write(change, 1)
            output.set_band_description(1, 'late_ndvi_minus_early_ndvi')
            output.update_tags(early_date=early_date.isoformat(), late_date=late_date.isoformat(),
                units='NDVI difference', decline_threshold=str(threshold), valid_basis='both dates AND supplied mask AND NDVI range',
                early_source_sha256=_hash(paths['early_ndvi']), late_source_sha256=_hash(paths['late_ndvi']), mask_source_sha256=_hash(paths['valid_mask']))
        records, polygons = [], []
        for geometry, _ in shapes(declined.astype('uint8'), mask=declined, transform=early.transform, connectivity=4):
            polygon = shape(geometry)
            selected = geometry_mask([geometry], out_shape=change.shape, transform=early.transform, invert=True) & declined
            values = change[selected]
            records.append({'candidate_id': len(records) + 1, 'pixel_count': int(values.size),
                'area_m2': float(values.size * pixel_area), 'mean_change': float(values.mean()), 'min_change': float(values.min()),
                'early_date': early_date.isoformat(), 'late_date': late_date.isoformat(), 'decline_threshold': threshold})
            polygons.append(polygon)
        columns = ('candidate_id', 'pixel_count', 'area_m2', 'mean_change', 'min_change', 'early_date', 'late_date', 'decline_threshold')
        candidates = gpd.GeoDataFrame({key: [row[key] for row in records] for key in columns}, geometry=polygons, crs=early.crs)
        candidates.to_file(context.output_path('candidates.gpkg'), layer='candidates', driver='GPKG', index=False, engine='pyogrio', geometry_type='Polygon')
        count = int(valid.sum())
        decline_count = int(declined.sum())
        statistics = {'early_date': early_date.isoformat(), 'late_date': late_date.isoformat(),
            'total_pixels': int(change.size), 'valid_pixels': count, 'invalid_pixels': int(change.size - count),
            'out_of_range_pixels': out_of_range, 'pixel_area_m2': pixel_area, 'valid_area_m2': count * pixel_area,
            'decline_pixels': decline_count, 'decline_area_m2': decline_count * pixel_area,
            'decline_fraction': decline_count / count if count else 0.0,
            'mean_change': float(change[valid].mean()) if count else None,
            'candidate_count': len(records), 'decline_threshold': threshold, 'crs': str(early.crs)}
    _write_csv(context.output_path('statistics.csv'), [statistics])
    quality = {'version': 1, 'status': 'passed' if count and not out_of_range else 'needs_review',
        'summary': f'共同有效{count}个像元，下降{decline_count}个，提取{len(records)}个植被变化候选面；面积为输入米制投影下的平面面积。',
        'metrics': {'validPixels': count, 'invalidPixels': statistics['invalid_pixels'], 'outOfRangePixels': out_of_range,
            'validAreaM2': statistics['valid_area_m2'], 'declineAreaM2': statistics['decline_area_m2'], 'candidateCount': len(records)},
        'knowledgeFacts': {'ndviChange': {'earlyDate': early_date.isoformat(), 'lateDate': late_date.isoformat(),
            'commonValidMaskApplied': True, 'rangeChecked': True, 'declineThreshold': threshold,
            'meanChange': statistics['mean_change'], 'sourceSha256': {key: _hash(path) for key, path in paths.items()},
            'interpretation': '两期植被变化线索；原因及长期状态结合背景、观测和更长时间序列解释'}}}
    Path(context.output_path('quality.json')).write_text(json.dumps(quality, ensure_ascii=False, allow_nan=False), encoding='utf-8')
