"""Actual fixed-script rendering; no catalog registration or database access."""

from dataclasses import replace
import hashlib
import io
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock, patch
import uuid

import numpy as np
from PIL import Image
import pytest
import rasterio
from rasterio.enums import ColorInterp
from rasterio.transform import from_bounds
from rasterio.warp import transform_bounds

from apps.compute import map_preview
from apps.compute.packages import ComputeError


@pytest.fixture
def output(settings, tmp_path):
    map_preview.clear_preview_cache()
    settings.PROJECT_CONFIG = replace(
        settings.PROJECT_CONFIG,
        app_data=tmp_path / "app",
    )
    source = settings.PROJECT_CONFIG.app_data / "compute/result.tif"
    source.parent.mkdir(parents=True)
    data = np.tile(np.linspace(-1, 1, 300, dtype="float32"), (200, 1))
    data[:50, :50] = -9999
    with rasterio.Env(GDAL_PAM_ENABLED="NO"):
        with rasterio.open(
            source,
            "w",
            driver="GTiff",
            width=300,
            height=200,
            count=1,
            dtype="float32",
            crs="EPSG:32645",
            nodata=-9999,
            transform=from_bounds(615864, 4444548.5, 615992, 4444676.5, 300, 200),
        ) as dst:
            dst.write(data, 1)
    return SimpleNamespace(
        id=7,
        task_id=uuid.uuid4(),
        label="NDVI计算结果",
        key="ndvi",
        task=SimpleNamespace(project_tag_id=1, status="succeeded"),
        kind="raster",
        expired=False,
        path="compute/result.tif",
        checksum=hashlib.sha256(source.read_bytes()).hexdigest(),
    )


def source_path(output) -> Path:
    return map_preview.app_path(output.path)


def replace_raster(
    output,
    crs="EPSG:4326",
    bounds=(87, 39, 88, 40),
    width=300,
    height=200,
    all_nodata=False,
):
    path = source_path(output)
    values = np.ones((height, width), dtype="float32")
    if all_nodata:
        values[:] = -9999
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="float32",
        crs=crs,
        nodata=-9999,
        transform=from_bounds(*bounds, width, height),
    ) as dst:
        dst.write(values, 1)
    output.checksum = hashlib.sha256(path.read_bytes()).hexdigest()


def test_preview_reprojects_transparency_and_keeps_source_read_only(output):
    original = source_path(output).read_bytes()
    original_stat = source_path(output).stat()
    png, metadata = map_preview.ensure_map_preview(output)
    assert metadata["outputId"] == output.id
    assert metadata["label"] == output.label
    with rasterio.open(source_path(output)) as src:
        expected = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
    assert metadata["bounds4326"] == pytest.approx(expected)
    west, south, east, north = expected
    assert metadata["imageCoordinates"] == [
        [west, north],
        [east, north],
        [east, south],
        [west, south],
    ]
    with Image.open(io.BytesIO(png)) as image:
        assert image.mode == "RGBA"
        pixels = np.asarray(image)
    assert np.any(pixels[..., 3] == 0)
    assert np.any(pixels[..., 3] == 255)
    assert source_path(output).read_bytes() == original
    assert source_path(output).stat().st_mtime_ns == original_stat.st_mtime_ns
    assert not source_path(output).with_suffix(".tif.aux.xml").exists()
    # Unit tests forbid database access, including silent creation of business rows.
    with patch.object(
        map_preview, "popen_cli", side_effect=AssertionError("cache miss")
    ):
        assert map_preview.ensure_map_preview(output) == (png, metadata)


def test_preview_caps_source_dimensions_and_toml_limit(output):
    replace_raster(output, width=1400, height=700)
    _, metadata = map_preview.ensure_map_preview(output)
    assert max(metadata["width"], metadata["height"]) == 1024
    with patch.object(map_preview, "runtime_max_raster_side_pixels", return_value=64):
        _, limited = map_preview.ensure_map_preview(output)
    assert max(limited["width"], limited["height"]) == 64


def test_all_nodata_stays_transparent(output):
    replace_raster(output, all_nodata=True)
    png, _ = map_preview.ensure_map_preview(output)
    with Image.open(io.BytesIO(png)) as image:
        assert not np.asarray(image)[..., 3].any()


def test_multi_band_result_uses_first_band_and_preserves_existing_alpha(output):
    path = source_path(output)
    values = np.full((4, 20, 30), 180, dtype="uint8")
    values[3] = 255
    values[3, :10, :10] = 0
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=30,
        height=20,
        count=4,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_bounds(87, 39, 88, 40, 30, 20),
    ) as dst:
        dst.write(values)
        dst.colorinterp = (
            ColorInterp.red,
            ColorInterp.green,
            ColorInterp.blue,
            ColorInterp.alpha,
        )
    output.checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    png, _ = map_preview.ensure_map_preview(output)
    with Image.open(io.BytesIO(png)) as image:
        rendered = np.asarray(image)
    assert np.any(rendered[..., 3] == 0)
    assert np.any(rendered[..., 3] == 255)
    assert path.read_bytes() and not path.with_suffix(".tif.aux.xml").exists()


@pytest.mark.parametrize(
    "field,value,detail,status",
    [
        ("expired", True, "已过期", 404),
        ("kind", "table", "栅格", 400),
        ("status", "running", "尚未成功", 400),
        ("path", "../other/result.tif", "路径无效", 404),
        ("path", "compute/missing.tif", "已不存在", 404),
    ],
)
def test_unavailable_or_unsafe_outputs_are_rejected(
    output, field, value, detail, status
):
    target = output.task if field == "status" else output
    setattr(target, field, value)
    with pytest.raises(ComputeError, match=detail) as captured:
        map_preview.ensure_map_preview(output)
    assert captured.value.status == status
    assert not map_preview.app_path("cache/compute-map-preview").exists()


@pytest.mark.parametrize(
    "crs,bounds,message",
    [
        (None, (87, 39, 88, 40), "缺少有效坐标系"),
        ("EPSG:4326", (170, 0, 190, 10), "日期变更线"),
        ("EPSG:4326", (-179, 0, 179, 10), "超过半球"),
        ("EPSG:4326", (87, 86, 88, 87), "纬度范围"),
    ],
)
def test_unsupported_georeferencing_has_actionable_error(output, crs, bounds, message):
    replace_raster(output, crs=crs, bounds=bounds)
    with pytest.raises(ComputeError, match=message):
        map_preview.ensure_map_preview(output)
    assert not list(map_preview.app_path("cache/compute-map-preview").rglob("*.png"))
    assert not list(map_preview.app_path("cache/compute-map-preview").rglob("*.part"))


def test_cache_identity_contains_project_task_output_file_rule_and_size(output):
    source = source_path(output)
    original = map_preview._fingerprint(
        output, source, 1024, map_preview._rules(output)
    )
    fingerprints = {original}
    for target, field, value in [
        (output.task, "project_tag_id", 9),
        (output, "task_id", uuid.uuid4()),
        (output, "id", 88),
        (output, "checksum", "b" * 64),
    ]:
        before = getattr(target, field)
        setattr(target, field, value)
        fingerprints.add(
            map_preview._fingerprint(output, source, 1024, map_preview._rules(output))
        )
        setattr(target, field, before)
    fingerprints.add(
        map_preview._fingerprint(output, source, 128, map_preview._rules(output))
    )
    fingerprints.add(
        map_preview._fingerprint(output, source, 1024, {"band": 1, "range": None})
    )
    source.touch()
    fingerprints.add(
        map_preview._fingerprint(output, source, 1024, map_preview._rules(output))
    )
    assert len(fingerprints) == 8


def test_different_projects_never_reuse_the_same_preview_cache(output):
    map_preview.ensure_map_preview(output)
    output.task.project_tag_id = 2
    actual_render = map_preview._render
    with patch.object(map_preview, "_render", wraps=actual_render) as render:
        map_preview.ensure_map_preview(output)
    render.assert_called_once()
    assert len(map_preview._CACHE) == 2


def test_source_content_modified_with_same_mtime_never_reuses_cached_preview(output):
    map_preview.ensure_map_preview(output)
    source = source_path(output)
    previous = source.stat()
    with source.open("r+b") as stream:
        stream.seek(-4, 2)
        stream.write(b"fake")
    os.utime(source, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    with pytest.raises(ComputeError, match="与登记内容不一致") as captured:
        map_preview.ensure_map_preview(output)
    assert captured.value.status == 409


def test_render_timeout_kills_child_and_removes_partial_cache(output):
    process = Mock()
    process.communicate.side_effect = [
        subprocess.TimeoutExpired("preview", 30),
        ("", ""),
    ]
    with patch.object(map_preview, "popen_cli", return_value=process):
        with pytest.raises(ComputeError, match="超时") as captured:
            map_preview.ensure_map_preview(output)
    assert captured.value.status == 503
    process.kill.assert_called_once()
    assert not list(map_preview.app_path("cache/compute-map-preview").rglob("*.part"))


def test_source_replaced_during_render_is_not_published(output):
    actual_render = map_preview._render

    def render_then_replace(*args):
        value = actual_render(*args)
        source_path(output).touch()
        return value

    with patch.object(map_preview, "_render", side_effect=render_then_replace):
        with pytest.raises(ComputeError, match="已更新") as captured:
            map_preview.ensure_map_preview(output)
    assert captured.value.status == 409
    assert not list(map_preview.app_path("cache/compute-map-preview").rglob("*.png"))


def test_memory_cache_is_bounded_and_never_keeps_png_files(output):
    original = source_path(output).read_bytes()
    root = map_preview.app_path("cache/compute-map-preview")
    with patch.object(map_preview, "MAX_MEMORY_CACHE_ENTRIES", 3):
        for number in range(5):
            output.id = number
            map_preview.ensure_map_preview(output)
    assert len(map_preview._CACHE) == 3
    assert not list(root.rglob("*.png"))
    assert not list(root.rglob("render-*"))
    assert source_path(output).read_bytes() == original
