"""Native CF observations keep temporal meaning, masks, units and source identity."""

import json
from pathlib import Path
from uuid import uuid4
import numpy as np
import pytest
import rasterio
from unittest.mock import patch
from apps.catalog.models import DataResource
from apps.compute.cube_inputs import materialize
from apps.compute.data import freeze_input
from apps.compute.models import ComputeTask, ComputeInput
from apps.compute.input_versions import stage_version
from apps.compute.native_cube_reader import Cube
from apps.compute.packages import ComputeError, validate_manifest
from apps.compute.services import validate_submission
from apps.core.storage import raster_source_path
from apps.projects.context import project_scope, ProjectScope
from tests.integration.test_compute import setup_compute  # noqa:F401

# ruff:noqa:F811
pytestmark = pytest.mark.django_db


def write_cube(path):
    path.mkdir(parents=True, exist_ok=True)
    metadata = {".zgroup": {"zarr_format": 2}, ".zattrs": {"crs": "EPSG:4326"}}
    arrays = {
        "time": (
            np.array([0, 8, 16, 24], dtype="<i8"),
            ["time"],
            {"units": "days since 2001-01-01"},
        ),
        "latitude": (np.array([0.125, -0.125], dtype="<f8"), ["latitude"], {}),
        "longitude": (np.array([0.125, 0.375, 0.625], dtype="<f8"), ["longitude"], {}),
        "gwis_ba": (
            np.stack([np.full((2, 3), index * 10, dtype="<f4") for index in range(4)]),
            ["time", "latitude", "longitude"],
            {"units": "hectares (ha)"},
        ),
        "fcci_ba": (
            np.full((4, 2, 3), 10, dtype="<f4"),
            ["time", "latitude", "longitude"],
            {"units": "hectares (ha)"},
        ),
        "gwis_ba_valid_mask": (np.array([1, 0, 1, 1], dtype="i1"), ["time"], {}),
        "fcci_ba_valid_mask": (np.ones(4, dtype="i1"), ["time"], {}),
    }
    for name, (array, dimensions, attrs) in arrays.items():
        directory = path / name
        directory.mkdir()
        schema = {
            "zarr_format": 2,
            "shape": list(array.shape),
            "chunks": list(array.shape),
            "dtype": array.dtype.str,
            "compressor": None,
            "fill_value": "NaN" if array.dtype.kind == "f" else None,
            "order": "C",
            "filters": None,
        }
        attributes = {**attrs, "_ARRAY_DIMENSIONS": dimensions}
        (directory / ".zarray").write_text(json.dumps(schema))
        (directory / ".zattrs").write_text(json.dumps(attributes))
        (directory / ".".join("0" for _ in array.shape)).write_bytes(array.tobytes())
        metadata[name + "/.zarray"] = schema
        metadata[name + "/.zattrs"] = attributes
    for name in (".zgroup", ".zattrs"):
        (path / name).write_text(json.dumps(metadata[name]))
    (path / ".zmetadata").write_text(
        json.dumps({"zarr_consolidated_format": 1, "metadata": metadata})
    )


def test_observation_preserves_invalid_periods_and_monthly_mean(tmp_path):
    path = tmp_path / "cube.zarr"
    write_cube(path)
    cube = Cube(path)
    values, report = cube.observation(
        "gwis_ba", 3, [0, -0.25, 0.75, 0.25], history=3, return_frames=True
    )
    assert np.isnan(values[0]).all() and report["series"][0]["value"] is None
    assert report["current"]["value"] == 180
    values, report = cube.observation(
        "fcci_ba", 3, [0, -0.25, 0.75, 0.25], history=3, return_frames=True
    )
    assert len(values) == 1 and report["current"]["value"] == 60
    assert (
        report["current"]["observedStart"] == "2001-01-01"
        and report["current"]["observedEnd"] == "2001-01-31"
    )


@pytest.mark.efficiency
def test_native_warm_slice_reuses_only_unchanged_selected_chunks(setup_compute):
    from apps.compute.cube_inputs import fingerprint

    env = setup_compute
    scope = ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    with project_scope(scope):
        path = raster_source_path("warm-cube.zarr")
        write_cube(path)
        resource = DataResource.objects.create(
            name="时序缓存验证",
            code="native-warm-cube",
            data_type="raster",
            file_format="ZARR",
            storage_path="original/warm-cube.zarr",
            coordinate_system="EPSG:4326",
            size_bytes=44000000000,
        )
        plan = Cube(path).plan("gwis_ba", 3, [0, -0.25, 0.75, 0.25], 3)
        plan["sourceFingerprint"] = fingerprint(path, plan)

        def prepare(name, selected):
            return stage_version(
                resource,
                "cube",
                env["tmp"] / name,
                lambda target: materialize(resource, target, selected),
                variant=selected,
            )

        first = prepare("cold.tif", plan)
        (path / "fcci_ba/0.0.0").write_bytes(b"unselected product changed")
        with patch.object(
            Cube, "observation", side_effect=AssertionError("Repeated decode")
        ):
            second = prepare("warm.tif", plan)
        assert not first["preparation"]["reused"]
        assert second["preparation"]["reused"]
        assert first["sha256"] == second["sha256"]
        alternative = Cube(path).plan("gwis_ba", 2, [0, -0.25, 0.75, 0.25], 2)
        alternative["sourceFingerprint"] = fingerprint(path, alternative)
        third = prepare("different-period.tif", alternative)
        assert not third["preparation"]["reused"]
        assert third["sha256"] != first["sha256"]
        (path / "gwis_ba/0.0.0").write_bytes(b"selected product changed")
        with pytest.raises(ComputeError, match="变化"):
            prepare("denied.tif", plan)
        assert not (env["tmp"] / "denied.tif").exists()


def test_native_container_is_frozen_as_source_bound_temporal_stack(
    setup_compute, tmp_path
):
    env = setup_compute
    scope = ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    with project_scope(scope):
        path = raster_source_path("cube.zarr")
        write_cube(path)
        resource = DataResource.objects.create(
            name="原生立方体",
            code="native-cube",
            data_type="raster",
            file_format="ZARR",
            storage_path="original/cube.zarr",
            coordinate_system="EPSG:4326",
            size_bytes=44000000000,
        )
        config = {
            "family": "seasfire_observation_v04",
            "variableParameter": "product",
            "timeParameter": "time_index",
            "historyParameter": "history",
        }
        manifest = json.loads(
            (
                Path(__file__).resolve().parents[3]
                / "examples/compute/spartina-rf/operator.yaml"
            ).read_text()
        )
        manifest["runtime"] = "python-geospatial-v1"
        manifest["inputs"] = [
            {
                "key": "cube",
                "label": "原生立方体",
                "kind": "raster",
                "required": True,
                "description": "原始Zarr时空观测",
                "fields": [],
                "crs": {"mode": "any"},
                "raster": {
                    "cube": config,
                    "window": ["west", "south", "east", "north"],
                },
            }
        ]
        for row, value in zip(manifest["parameters"], [0, -0.25, 0.75, 0.25]):
            row["default"] = value
        manifest["parameters"] += [
            {
                "key": key,
                "label": key,
                "type": kind,
                "default": value,
                "help": "明确选择已登记变量和时期",
                "agent": {"adjustable": False, "advice": "沿用用户选择"},
                **(
                    {"choices": ["gwis_ba", "fcci_ba"]}
                    if kind == "enum"
                    else {"min": minimum, "max": maximum}
                ),
            }
            for key, kind, value, minimum, maximum in [
                ("product", "enum", "gwis_ba", 0, 1),
                ("time_index", "integer", 3, 0, 965),
                ("history", "integer", 3, 1, 12),
            ]
        ]
        env["version"].manifest = validate_manifest(manifest)
        env["version"].save()
        parameters = {
            "product": "gwis_ba",
            "time_index": 3,
            "history": 3,
            "west": 0,
            "south": -0.25,
            "east": 0.75,
            "north": 0.25,
        }
        request = {
            "name": "原生观测",
            "idempotencyKey": uuid4().hex,
            "versionId": env["version"].pk,
            "inputs": {"cube": resource.pk},
            "parameters": parameters,
        }
        info = validate_submission(env["owner"], request)["resources"][0][2]
        assert info["bands"] == 3 and info["sizeBytes"] < 100000
        task = ComputeTask.objects.create(
            owner=env["owner"],
            version=env["version"],
            parameters=parameters,
            status="queued",
            idempotency_key=uuid4().hex,
            request_hash="f" * 64,
        )
        record = ComputeInput.objects.create(
            task=task,
            key="cube",
            resource=resource,
            snapshot={**info, "updatedAt": resource.updated_at.isoformat()},
        )
        output = tmp_path / "task"
        output.mkdir()
        frozen = freeze_input(record, output)
        assert frozen["resourceId"] == resource.pk
        with rasterio.open(output / "cube.tif") as dataset:
            assert (
                dataset.count == 3
                and dataset.tags()["stisp_input_semantics"]
                == "temporal_observation_stack_v1"
            )
            assert np.all(dataset.read(1) == -9999)
            assert np.all(dataset.read(3) == 30)
        import importlib.util
        from types import SimpleNamespace
        import sys

        root = Path(__file__).resolve().parents[3]
        sys.path.insert(0, str(root / "deploy/compute"))
        module_spec = importlib.util.spec_from_file_location(
            "wildfire_observe_example",
            root / "examples/compute/wildfire-observe/main.py",
        )
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        destination = tmp_path / "results"
        destination.mkdir()
        context = SimpleNamespace(
            inputs={"cube": {"resourceId": resource.pk, "sha256": frozen["sha256"]}},
            input_path=lambda _: output / "cube.tif",
            output_path=lambda name: destination / name,
        )
        module.run(context)
        facts = json.loads((destination / "result.json").read_text())
        assert facts["statistics"]["burned_area_ha"] == 180
        assert facts["series"][0]["value"] is None
        with rasterio.open(destination / "classification.tif") as image:
            assert image.nodata == 255 and image.colormap(1)[1][:3] == (255, 225, 156)
        chunk = path / "gwis_ba/0.0.0"
        chunk.write_bytes(b"changed")
        with pytest.raises(ComputeError):
            materialize(resource, tmp_path / "changed.tif", info["cubeInput"])
