"""Observation dates and usage are scoped metadata, never ingestion provenance."""

from datetime import date
from unittest.mock import patch
import pytest
from django.contrib.auth.models import Permission
from apps.catalog.models import (
    DataResource,
    ResourceObservationMetadata,
)
from apps.catalog.monitoring_metadata import update_metadata
from apps.core.storage import raster_source_path
from apps.projects.context import ProjectScope, project_scope
from tests.integration.test_compute import setup_compute  # noqa:F401
from tests.integration.test_native_cube_inputs import write_cube

# ruff:noqa:F811
pytestmark = pytest.mark.django_db


def source(env, **extra):
    with project_scope(
        ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    ):
        return DataResource.objects.create(
            name="登记资料",
            code="temporal-source",
            data_type="raster",
            file_format="GTIFF",
            maintainer=env["owner"],
            **extra,
        )


def own_scope(env):
    return project_scope(
        ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    )


def endpoint(resource):
    return f"/api/catalog/resources/{resource.pk}/observation-metadata/"


def test_owner_metadata_preserves_ingestion_and_unknown_precision(setup_compute):
    env = setup_compute
    env["owner"].user_permissions.add(
        Permission.objects.get(
            content_type__app_label="catalog", codename="change_dataresource"
        )
    )
    resource = source(env)
    response = env["client"].patch(
        endpoint(resource),
        {
            "precision": "month",
            "startsAt": "2026-03-01",
            "endsAt": "2026-03-31",
            "usages": [{"scene": "spartina", "purpose": "input"}],
        },
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].pk),
    )
    assert response.status_code == 200, response.content
    assert response.json()["period"] == {
        "startsAt": "2026-03-01",
        "endsAt": "2026-03-31",
        "precision": "month",
    }
    with own_scope(env):
        resource.refresh_from_db()
        assert resource.data_date is None and not resource.is_compute_result
        stamp = resource.updated_at
    response = env["client"].patch(
        endpoint(resource),
        {"usages": [{"scene": "spartina", "purpose": "input"}]},
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].pk),
    )
    assert response.status_code == 200
    assert response.json()["period"]["startsAt"] == "2026-03-01"
    with own_scope(env):
        resource.refresh_from_db()
        assert resource.updated_at == stamp


@pytest.mark.parametrize(
    "payload",
    [
        {"family": {}},
        {"precision": {}, "startsAt": None},
        {"usages": [{"scene": [], "purpose": "input"}]},
        {"precision": "month", "startsAt": "2026-03-15", "endsAt": "2026-03-31"},
        {"precision": "day", "startsAt": "2026-02-30", "endsAt": "2026-02-30"},
    ],
)
def test_metadata_rejects_invalid_body_without_partial_rows(setup_compute, payload):
    env = setup_compute
    resource = source(env)
    env["owner"].user_permissions.add(
        Permission.objects.get(
            content_type__app_label="catalog", codename="change_dataresource"
        )
    )
    response = env["client"].patch(
        endpoint(resource),
        payload,
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].pk),
    )
    assert response.status_code == 400, response.content
    with own_scope(env):
        assert not ResourceObservationMetadata.objects.filter(
            resource=resource
        ).exists()


def test_metadata_enforces_membership_owner_and_private_visibility(setup_compute):
    env = setup_compute
    resource = source(env)
    assert env["client"].get(endpoint(resource)).status_code == 400
    assert env["client"].get(
        endpoint(resource), HTTP_X_PROJECT_ID=str(env["other_project"].pk)
    ).status_code in {403, 404}
    # Browsing a resource does not grant editing of its observation metadata.
    assert (
        env["client"]
        .patch(
            endpoint(resource),
            {},
            content_type="application/json",
            HTTP_X_PROJECT_ID=str(env["project"].pk),
        )
        .status_code
        == 403
    )
    with own_scope(env):
        resource.owner_only = True
        resource.maintainer = env["outsider"]
        resource.save(update_fields=["owner_only", "maintainer"])
    assert (
        env["client"]
        .get(endpoint(resource), HTTP_X_PROJECT_ID=str(env["project"].pk))
        .status_code
        == 404
    )


def test_native_index_uses_real_coordinates_and_get_never_opens_cube(setup_compute):
    env = setup_compute
    env["owner"].user_permissions.add(
        Permission.objects.get(
            content_type__app_label="catalog", codename="change_dataresource"
        )
    )
    with own_scope(env):
        path = raster_source_path("indexed.zarr")
        write_cube(path)
        resource = DataResource.objects.create(
            name="真实原生立方体",
            code="indexed-native",
            data_type="raster",
            file_format="ZARR",
            storage_path="original/indexed.zarr",
            maintainer=env["owner"],
        )
        value = update_metadata(
            env["owner"],
            resource,
            {"usages": [{"scene": "wildfire", "purpose": "input"}]},
        )
        observation = ResourceObservationMetadata.objects.get(resource=resource)
        points = list(observation.time_points.all())
        assert len(points) == 4 and points[1].starts_at == date(2001, 1, 9)
        assert "gwis_ba" not in points[1].available_products
        assert value["sourceSchema"]["timeCount"] == 4
    with patch(
        "apps.compute.native_cube_reader.Cube",
        side_effect=AssertionError("GET opened raw cube"),
    ):
        response = env["client"].get(
            endpoint(resource), HTTP_X_PROJECT_ID=str(env["project"].pk)
        )
        assert response.status_code == 200, response.content
        response = env["client"].get(
            "/api/catalog/observation-metadata/",
            {"ids": str(resource.pk)},
            HTTP_X_PROJECT_ID=str(env["project"].pk),
        )
        assert response.status_code == 200 and len(response.json()["items"]) == 1
