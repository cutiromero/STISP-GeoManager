"""Monitor candidate dates follow registered sources and model input contracts."""

from datetime import date
from unittest.mock import patch
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from apps.catalog.models import (
    DataResource,
    ResourceObservationMetadata,
    ResourceMonitoringUsage,
    ResourceObservationTimePoint,
)
from apps.catalog.monitoring_metadata import metadata_batch
from apps.ecology.source_catalog import input_sets, monitoring_sources, source_times
from apps.projects.context import project_scope, ProjectScope
from tests.integration.test_compute import setup_compute  # noqa:F401
from tests.integration.test_wildfire_observation import enable

# ruff:noqa:F811
pytestmark = pytest.mark.django_db


def asset(identity, month, year=2026):
    return {
        "resource": {"id": identity, "name": f"影像{identity}"},
        "metadata": {
            "resourceVersion": f"v{identity}",
            "collectionKey": "one",
            "period": {
                "startsAt": f"{year}-{month:02d}-01",
                "endsAt": f"{year}-{month:02d}-28",
                "precision": "month",
            },
            "sourceSchema": {
                "kind": "raster",
                "bands": 16,
                "bandTypes": ["Float32"] * 16,
                "coordinateSystem": "EPSG:4326",
                "geoTransform": [120, 0.001, 0, 32, 0, -0.001],
            },
        },
    }


def test_new_dates_form_rolling_inputs_without_filename_or_year_constants():
    method = {
        "versionId": 8,
        "inputs": [
            {
                "key": key,
                "required": True,
                "kind": "raster",
                "bandCount": 16,
                "minBands": 16,
                "dtypes": ["float32"],
                "nativeCube": False,
            }
            for key in ["a", "b", "c"]
        ],
    }
    values = [asset(11, 1), asset(12, 4), asset(13, 7), asset(14, 10)]
    sets = input_sets(values, method, "spartina")
    assert len(sets) == 2 and sets[0]["inputs"] == {"a": 12, "b": 13, "c": 14}
    assert sets[1]["inputs"] == {"a": 11, "b": 12, "c": 13}
    assert "2026-10" in sets[0]["label"]
    changed = [*values[:3], asset(99, 10)]
    assert input_sets(changed, method, "spartina")[0]["id"] != sets[0]["id"]
    other = asset(15, 11)
    other["metadata"]["collectionKey"] = "different"
    assert len(input_sets([*values, other], method, "spartina")) == 2


def test_single_input_method_accepts_untimed_registered_images():
    value = asset(11, 1)
    value["metadata"]["period"] = None
    method = {
        "versionId": 1,
        "inputs": [
            {
                "key": "image",
                "kind": "raster",
                "required": True,
                "bandCount": 16,
                "minBands": 1,
                "nativeCube": False,
            }
        ],
    }
    sets = input_sets([value], method, "landcover")
    assert (
        len(sets) == 1
        and sets[0]["startsAt"] is None
        and sets[0]["inputs"] == {"image": 11}
    )


def test_source_catalog_reads_metadata_only_and_excludes_results(setup_compute):
    env = setup_compute
    scope = ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    with project_scope(scope):
        enable(env)
        for identity, purpose in [("raw", "input"), ("classified", "result")]:
            resource = DataResource.objects.create(
                name=identity, code=identity, data_type="raster", file_format="ZARR"
            )
            observation = ResourceObservationMetadata.objects.create(
                resource=resource,
                family="seasfire",
                collection_key="fire",
                starts_at=date(2022, 1, 1),
                ends_at=date(2024, 1, 1),
                precision="interval",
                source_schema={"kind": "native_cube", "timeCount": 2},
                index_version="a" * 64,
            )
            ResourceMonitoringUsage.objects.create(
                resource=resource, scene="wildfire", purpose=purpose
            )
            ResourceObservationTimePoint.objects.bulk_create(
                [
                    ResourceObservationTimePoint(
                        project_tag_id=env["project"].pk,
                        observation=observation,
                        ordinal=1000,
                        starts_at=date(2022, 1, 1),
                        ends_at=date(2022, 1, 8),
                        available_products=["gwis_ba"],
                        source_version="a" * 64,
                    ),
                    ResourceObservationTimePoint(
                        project_tag_id=env["project"].pk,
                        observation=observation,
                        ordinal=2000,
                        starts_at=date(2023, 1, 1),
                        ends_at=date(2023, 1, 8),
                        available_products=["gwis_ba"],
                        source_version="a" * 64,
                    ),
                ]
            )
        with patch(
            "apps.compute.native_cube_reader.Cube",
            side_effect=AssertionError("Catalog opened cube"),
        ):
            data = monitoring_sources(env["owner"], "wildfire")
            assert (
                len(data["assets"]) == 1
                and data["assets"][0]["resource"]["code"] == "raw"
            )
            resource_id = data["assets"][0]["resource"]["id"]
            times = source_times(env["owner"], "wildfire", resource_id, 2023, "gwis_ba")
            assert times["items"][0]["ordinal"] == 2000
            assert (
                source_times(env["owner"], "wildfire", resource_id, 2023, "gfed_ba")[
                    "items"
                ]
                == []
            )
        DataResource.objects.filter(pk=resource_id).update(
            owner_only=True, maintainer=env["outsider"]
        )
        assert monitoring_sources(env["owner"], "wildfire")["assets"] == []


@pytest.mark.efficiency
def test_batch_roles_have_bounded_queries_and_stay_live(setup_compute):
    env = setup_compute
    with project_scope(
        ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    ):
        resources = DataResource.objects.bulk_create(
            [
                DataResource(
                    project_tag_id=env["project"].pk,
                    name=f"来源{i}",
                    code=f"source-{i}",
                    data_type="raster",
                    maintainer=env["owner"],
                )
                for i in range(30)
            ]
        )
        # Warm request-local group/permission facts, never resource ACL rows.
        metadata_batch(env["owner"], [resources[0].pk])
        with CaptureQueriesContext(connection) as one:
            metadata_batch(env["owner"], [resources[0].pk])
        with CaptureQueriesContext(connection) as many:
            metadata_batch(env["owner"], [row.pk for row in resources])
        assert len(many) <= len(one) + 1
        DataResource.objects.filter(pk=resources[0].pk).update(
            owner_only=True, maintainer=env["outsider"]
        )
        assert metadata_batch(env["owner"], [resources[0].pk]) == []
