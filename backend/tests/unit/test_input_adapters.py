"""Real category conversion, open-ended geology kernels and domain-neutral plans."""

import hashlib
from pathlib import Path
import runpy
from types import SimpleNamespace
from datetime import datetime, timezone

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from shapely.geometry import box

from apps.core.data_adapters import vector_class_masks
from apps.business_flows.input_adapters import plan_inputs
from apps.compute.packages import validate_manifest
from tests.unit.test_geology_multi_algorithms import (
    fixture,
    Context,
    check,
    load,
    approval_context,
    read,
    X,
    Y,
)

ROOT = Path(__file__).resolve().parents[3]
CLASSES = [
    "赤铁矿化",
    "白云石化",
    "黄铁矿化",
    "绢云母化",
    "高岭石化",
    "石英_脉",
    "萤石化",
]


def vector_source(path, names):
    gpd.GeoDataFrame(
        {"mineral_name": names, "code": list(range(len(names)))},
        geometry=[box(X + 100, Y + 100, X + 900, Y + 900) for _ in names],
        crs=32646,
    ).to_file(path, layer="classes", driver="GPKG", index=False)
    return path


def test_generic_vector_adapter_preserves_any_class_and_original_file(tmp_path):
    names = ["森林", "农田", "居民地", "水体", "湿地", "裸地", "冰雪"]
    source = vector_source(tmp_path / "landcover.gpkg", names)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    result = vector_class_masks(
        source,
        tmp_path / "landcover.tif",
        "mineral_name",
        resolution=50,
        target_epsg=32646,
    )
    assert result["classCount"] == 7
    with rasterio.open(tmp_path / "landcover.tif") as data:
        assert set(data.descriptions) == set(names) and data.count == 7
        assert all(np.count_nonzero(data.read(band) == 1) > 0 for band in range(1, 8))
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_unknown_geology_classes_survive_check_apply_and_recheck(tmp_path):
    initial, _ = fixture(tmp_path)
    source = vector_source(tmp_path / "minerals.gpkg", CLASSES)
    masks = tmp_path / "mineral_masks.tif"
    vector_class_masks(source, masks, "mineral_name", resolution=50, target_epsg=32646)
    with rasterio.open(masks, "r+") as stream:
        values = stream.read(1)
        values[0, 0] = 255
        stream.write(values, 1)
    original = hashlib.sha256(masks.read_bytes()).hexdigest()
    initial.inputs = {
        key: value
        for key, value in initial.inputs.items()
        if key not in {"hematite", "chlorite", "hydromica", "calcite", "dolomite"}
    }
    initial.inputs["alteration_stack"] = masks
    findings, _ = check(initial)
    quality = read(initial.output_path("alteration_quality.csv"))
    assert len(quality) == 7
    edited = approval_context(
        tmp_path, initial, findings, {row["issue_id"]: "keep" for row in findings}
    )
    load("apply")(edited)
    corrected = edited.output_path("alteration_stack_corrected.tif")
    weights = edited.output_path("alteration_stack_weight.tif")
    with (
        rasterio.open(masks) as before,
        rasterio.open(corrected) as after,
        rasterio.open(weights) as weight,
    ):
        assert set(after.descriptions) == set(CLASSES)
        assert after.count == 7 and weight.count == 7
        np.testing.assert_array_equal(
            before.read(masked=True).filled(255), after.read(masked=True).filled(255)
        )
        np.testing.assert_array_equal(before.read_masks(), after.read_masks())
    recheck = Context(
        tmp_path / "recheck",
        {
            **initial.inputs,
            "lithology": edited.output_path("lithology.gpkg"),
            "faults": edited.output_path("faults.gpkg"),
            "alteration_stack": corrected,
            "alteration_stack_weight": weights,
        },
        initial.parameters,
    )
    check(recheck)
    assert len(read(recheck.output_path("alteration_quality.csv"))) == 7
    relations = Context(
        tmp_path / "relations",
        {**initial.inputs, "faults": edited.output_path("faults.gpkg")},
        initial.parameters,
    )
    load("relations")(relations)
    prospect = Context(
        tmp_path / "prospect",
        {
            **recheck.inputs,
            "intersections": relations.output_path("intersections.gpkg"),
        },
        {
            "min_zone_area_km2": 0.01,
            "min_core_area_km2": 0.001,
            "core_score_min": 0.5,
            "peripheral_min_density": 0.0001,
        },
    )
    load("prospect")(prospect)
    assert prospect.output_path("after_zones.gpkg").is_file()
    assert prospect.output_path("prospect_support.tif").is_file()
    assert hashlib.sha256(masks.read_bytes()).hexdigest() == original
    import multi_io

    assert len(multi_io.RASTERS) == 5, "The per-job class dictionary must be restored"


def test_band_label_change_cannot_reuse_an_old_approval(tmp_path):
    initial, _ = fixture(tmp_path)
    masks = tmp_path / "classes.tif"
    vector_class_masks(
        vector_source(tmp_path / "source.gpkg", CLASSES),
        masks,
        "mineral_name",
        resolution=50,
        target_epsg=32646,
    )
    initial.inputs = {
        key: value
        for key, value in initial.inputs.items()
        if key not in {"hematite", "chlorite", "hydromica", "calcite", "dolomite"}
    }
    initial.inputs["alteration_stack"] = masks
    findings, _ = check(initial)
    edited = approval_context(
        tmp_path, initial, findings, {row["issue_id"]: "keep" for row in findings}
    )
    with rasterio.open(masks, "r+") as stream:
        stream.set_band_description(1, "新的类别")
    with pytest.raises(ValueError):
        load("apply")(edited)


def test_registered_capabilities_plan_for_unrelated_data_types():
    builder = runpy.run_path(str(ROOT / "examples/compute/input-adapters/build.py"))
    versions = []
    for index, key in enumerate(builder["SPECS"], 1):
        manifest = validate_manifest(builder["manifest"](key))
        versions.append(
            SimpleNamespace(
                pk=index,
                algorithm_id=index,
                manifest=manifest,
                checksum=str(index),
                algorithm=SimpleNamespace(name=manifest["name"]),
            )
        )
    source = SimpleNamespace(
        pk=91,
        data_type="raster",
        name="温度观测",
        updated_at=datetime.now(timezone.utc),
    )
    requirement = [
        {
            "key": "observations",
            "dataTypes": ["table"],
            "requiredFields": ["mean"],
            "semanticType": "raster_band_statistics_v1",
        }
    ]
    planned = plan_inputs(
        None,
        requirement,
        {"observations": (source, {"bands": 2, "fields": []})},
        available=versions,
    )
    assert planned["ready"] and planned["items"][0]["targetType"] == "table"
    assert planned["items"][0]["versionId"] == 3
    vector = SimpleNamespace(
        pk=92, data_type="vector", name="土地分类", updated_at=source.updated_at
    )
    planned = plan_inputs(
        None,
        [
            {
                "key": "classes",
                "dataTypes": ["raster"],
                "requiredFields": [],
                "semanticType": "class_mask_stack_v1",
            }
        ],
        {"classes": (vector, {"fields": ["mineral_name", "code"]})},
        available=versions,
    )
    assert (
        planned["ready"]
        and planned["items"][0]["parameters"]["category_field"] == "mineral_name"
    )


def test_ambiguous_fields_require_a_choice_not_a_guess():
    builder = runpy.run_path(str(ROOT / "examples/compute/input-adapters/build.py"))
    manifest = validate_manifest(builder["manifest"]("input-vector-class-masks"))
    version = SimpleNamespace(
        pk=1,
        algorithm_id=1,
        manifest=manifest,
        checksum="a",
        algorithm=SimpleNamespace(name="分类栅格化"),
    )
    source = SimpleNamespace(
        pk=1, data_type="vector", name="分类资料", updated_at=datetime.now(timezone.utc)
    )
    planned = plan_inputs(
        None,
        [
            {
                "key": "classes",
                "dataTypes": ["raster"],
                "requiredFields": [],
                "semanticType": "class_mask_stack_v1",
            }
        ],
        {"classes": (source, {"fields": ["name_a", "name_b"]})},
        available=[version],
    )
    assert planned["ready"] is False and planned["items"][0]["missingParameters"] == [
        "category_field"
    ]


def test_conditional_parameters_use_the_same_activation_rules_as_submission():
    from apps.business_flows.input_adapters import _parameters

    manifest = validate_manifest(
        {
            "schemaVersion": 1,
            "identifier": "conditional-adapter",
            "name": "条件转换",
            "version": "1.0.0",
            "description": "条件参数",
            "author": "STISP",
            "runtime": "python-geospatial-v1",
            "agent": {"enabled": True},
            "inputs": [{"key": "source", "label": "来源", "kind": "table"}],
            "outputs": [
                {
                    "key": "prepared",
                    "label": "结果",
                    "kind": "table",
                    "file": "prepared.csv",
                }
            ],
            "parameters": [
                {"key": "filter", "label": "筛选", "type": "boolean", "default": False},
                {
                    "key": "field",
                    "label": "筛选字段",
                    "type": "field",
                    "input": "source",
                    "when": {"key": "filter", "equals": True},
                },
            ],
            "inputAdapter": {
                "inputKey": "source",
                "outputKey": "prepared",
                "sourceKind": "table",
                "targetKind": "table",
            },
        }
    )
    version = SimpleNamespace(manifest=manifest)
    params, missing = _parameters(version, {"fields": ["region"]}, {})
    assert params == {"filter": False} and missing == []
    params, missing = _parameters(version, {"fields": ["region"]}, {"filter": True})
    assert missing == ["field"]


def test_empty_class_collection_does_not_create_five_invented_minerals(tmp_path):
    from apps.core.data_adapters import combine_masks

    initial, _ = fixture(tmp_path)
    path = tmp_path / "empty.tif"
    result = combine_masks(
        [], path, bounds=[X, Y, X + 1000, Y + 1000], crs="EPSG:32646", resolution=50
    )
    assert result["classCount"] == 0
    initial.inputs = {
        key: value
        for key, value in initial.inputs.items()
        if key not in {"hematite", "chlorite", "hydromica", "calcite", "dolomite"}
    }
    initial.inputs["alteration_stack"] = path
    findings, _ = check(initial)
    assert read(initial.output_path("alteration_quality.csv")) == []
    edited = approval_context(
        tmp_path, initial, findings, {row["issue_id"]: "keep" for row in findings}
    )
    load("apply")(edited)
    with rasterio.open(edited.output_path("alteration_stack_corrected.tif")) as data:
        assert data.tags()["stisp_empty_collection"] == "1"
        assert not np.any(data.read(1))
