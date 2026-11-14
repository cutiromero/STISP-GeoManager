"""Observation provenance, physical units and metadata-only time catalog."""

import sqlite3
import pytest
from apps.catalog.models import DataResource, DataResourceGroup
from apps.core.storage import table_data_path
from apps.ecology.monitoring import monitoring_snapshot
from apps.ecology.wildfire import register_import, observation_catalog
from apps.projects.context import project_scope, ProjectScope
from apps.projects.features import set_feature
from apps.projects.models import ProjectFeature
from tests.integration.test_landcover_monitoring import imported  # noqa:F401
from tests.integration.test_compute import setup_compute  # noqa:F401

# ruff:noqa:F811
pytestmark = pytest.mark.django_db


def enable(env):
    feature, _ = ProjectFeature.objects.get_or_create(key="ecology_monitor")
    set_feature(
        env["admin"],
        feature,
        project=env["project"],
        enabled=True,
        config={
            "title": "野火观测",
            "source": "remote_sensing_products",
            "scenes": ["wildfire"],
            "initialView": {"center": [130, -25], "zoom": 0.3, "regionZoom": 4},
        },
    )


def test_real_observation_import_has_no_fabricated_model_or_pixel_area_conversion(
    imported,
):
    env, task, source, record = imported
    with project_scope(env["scope"]):
        enable(env)
        type(task.version.algorithm)._base_manager.filter(
            pk=task.version.algorithm_id
        ).update(identifier="wildfire-observe")
        facts = {
            "product": "gwis_ba",
            "unit": "ha",
            "periodMode": "8day",
            "current": {
                "observedStart": "2019-12-27",
                "observedEnd": "2019-12-31",
                "value": 10,
                "validCells": 1,
                "activeCells": 1,
                "unit": "ha",
            },
            "series": [
                {
                    "observedStart": "2019-12-27",
                    "observedEnd": "2019-12-31",
                    "value": 10,
                    "validCells": 1,
                    "activeCells": 1,
                    "unit": "ha",
                }
            ],
            "activeCells": 1,
            "validCells": 1,
            "gridCells": 1,
            "grid": {
                "width": 1,
                "height": 1,
                "transform": [112, 0.25, 0, -10, 0, -0.25],
                "crs": "EPSG:4326",
            },
            "legend": [
                {"code": 0, "name": "零", "rgba": [0, 0, 0, 0]},
                {"code": 1, "name": "0–100 ha", "rgba": [255, 225, 156, 255]},
                {"code": 255, "name": "缺测", "rgba": [0, 0, 0, 0]},
            ],
            "statistics": {
                "burned_area_ha": 10,
                "frp_w_m2": None,
                "valid_coverage_percent": 100,
            },
        }
        output = record.output
        output.key = "observation"
        output.metadata = {
            **output.metadata,
            "knowledgeFacts": {"wildfireObservation": facts},
        }
        output.save()
        product, created = register_import(record.pk)
        assert created
        assert register_import(record.pk)[1] is False
        item = monitoring_snapshot(env["owner"], "wildfire")["items"][0]
        assert item["kind"] == "observation" and item["model"] is None
        assert item["statistics"]["burned_area_ha"] == 10
        assert item["observedEnd"] == "2019-12-31"
        assert item["provenance"]["taskId"] == str(task.pk)
        source.status = "inactive"
        source.save()
        assert monitoring_snapshot(env["owner"], "wildfire")["items"] == []


def test_catalog_uses_registered_time_table_and_preserves_year_end_window(
    setup_compute, monkeypatch
):
    env = setup_compute
    scope = ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    with project_scope(scope):
        enable(env)
        group = DataResourceGroup.objects.create(name="野火原始资料")
        DataResource.objects.create(
            name="原始立方体",
            code="wildfire-seasfire-cube-test",
            data_type="raster",
            file_format="ZARR",
            storage_path="original/not-opened.zarr",
            coordinate_system="EPSG:4326",
            inventory_group=group,
            item_count=966,
        )
        table = "wildfire_seasfire_time_test"
        resource = DataResource.objects.create(
            name="时间索引",
            code="fire-time",
            data_type="table",
            file_format="SQLITE",
            storage_path=table,
            inventory_group=group,
            item_count=3,
        )
        path = table_data_path("data.sqlite")
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute(
                "CREATE TABLE "
                + table
                + " (time_index INTEGER,date TEXT,gwis_ba_valid_mask INTEGER,gfed_ba_valid_mask INTEGER,fcci_ba_valid_mask INTEGER)"
            )
            db.executemany(
                "INSERT INTO " + table + " VALUES (?,?,?,?,?)",
                [
                    (0, "2001-01-01", 0, 1, 1),
                    (1, "2001-12-27", 0, 1, 1),
                    (2, "2002-01-01", 1, 1, 1),
                ],
            )
        from osgeo import gdal

        monkeypatch.setattr(
            gdal,
            "OpenEx",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("Cube pixels must not open in catalog")
            ),
        )
        result = observation_catalog(env["owner"])
        assert result["timeIndexResource"]["id"] == resource.pk
        assert result["times"][1]["endDate"] == "2001-12-31"
        assert "gwis_ba" not in result["times"][0]["validProducts"]
        assert "gwis_ba" in result["times"][2]["validProducts"]
        resource.owner_only = True
        resource.maintainer = env["outsider"]
        resource.save()
        assert observation_catalog(env["owner"])["times"] == []


def test_wildfire_flow_keeps_native_cube_and_observation_contract(setup_compute):
    import json
    from pathlib import Path
    from apps.compute.packages import validate_manifest
    from apps.business_flows.definitions import normalize_definition
    from apps.business_flows.wildfire import definition
    from apps.business_flows.management.commands.register_wildfire import (
        Command as WildfireCommand,
    )
    from apps.business_flows.management.commands.register_spartina import (
        Command as SpartinaCommand,
    )

    env = setup_compute
    version = env["version"]
    version.manifest = validate_manifest(
        json.loads(
            (
                Path(__file__).resolve().parents[3]
                / "examples/compute/wildfire-observe/operator.yaml"
            ).read_text()
        )
    )
    version.save()
    with project_scope(
        ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    ):
        value = normalize_definition(definition(version.pk))
    assert [row["key"] for row in value["inputRequirements"]] == ["cube"]
    operator = next(row for row in value["nodes"] if row["kind"] == "operator")
    assert operator["parameters"]["product"] == "gwis_ba"
    assert set(operator["contract"]["importOutputs"]) == {
        "observation",
        "classification",
        "statistics",
        "series",
    }
    assert (
        WildfireCommand.source_folder == "wildfire-observe"
        and WildfireCommand.default_inputs == {"cube": 1475}
    )
    assert SpartinaCommand.source_folder == "spartina-rf" and set(
        SpartinaCommand.default_inputs
    ) == {"march", "august", "december"}
