"""Ordinary catalogs hide explicit internal packets without changing bound reads."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from apps.catalog.models import DataResource, MapLayer


pytestmark = pytest.mark.django_db


@pytest.fixture
def catalog_client(client):
    user = get_user_model().objects.create_user(username="internal-catalog-owner")
    user.user_permissions.add(
        Permission.objects.get(content_type__app_label="core", codename="browse_data"),
        Permission.objects.get(
            content_type__app_label="catalog", codename="view_dataresource"
        ),
    )
    client.force_login(user)
    return client, user


def resource(user, *, source="用户导入", code=None, name="同名 test 演示资料"):
    item = DataResource.objects.create(
        name=name,
        code=code or "catalog-" + uuid4().hex,
        data_type="vector",
        coordinate_system="EPSG:4326",
        source=source,
        maintainer=user,
    )
    layer = MapLayer.objects.create(
        name=name,
        code="layer-" + uuid4().hex,
        layer_type="vector",
        data_resource=item,
        is_active=True,
    )
    return item, layer


def assert_catalog_boundary(client, hidden, visible):
    response = client.get("/api/catalog/resources/", HTTP_X_PROJECT_ID="1")
    assert response.status_code == 200, response.content
    ids = {item["id"] for item in response.json()["items"]}
    assert hidden[0].id not in ids and visible[0].id in ids

    response = client.get("/api/search/", {"q": "同名"}, HTTP_X_PROJECT_ID="1")
    assert response.status_code == 200, response.content
    ids = {item["id"] for item in response.json()["resources"]}
    assert hidden[0].id not in ids and visible[0].id in ids

    response = client.get("/api/layers/", HTTP_X_PROJECT_ID="1")
    assert response.status_code == 200, response.content
    ids = {item["id"] for item in response.json()["items"]}
    assert hidden[1].id not in ids and visible[1].id in ids

    response = client.get("/api/admin/data/resources/", HTTP_X_PROJECT_ID="1")
    assert response.status_code == 200, response.content
    ids = {item["id"] for item in response.json()["items"]}
    assert hidden[0].id not in ids and visible[0].id in ids
    # Catalog filtering does not remove or mutate the original bound material.
    assert DataResource.objects.get(pk=hidden[0].id).source == hidden[0].source


@pytest.mark.parametrize(
    "source",
    [
        "workflow-upload:batch",
        "workflow-working:workflow:lithology",
        "geology-multi-frozen-rules:workflow",
        "geology-multi-approved:workflow",
        "demo-changes:workflow",
        "geology-reference:case",
        "geology-case-reference-20261012:case",
        "geology-multi-reference:case",
        "geology-multi-evaluation:case",
        "geology-review-reference:case",
        "geology-review-acceptance:case",
    ],
)
def test_explicit_internal_sources_are_hidden_across_catalogs(catalog_client, source):
    client, user = catalog_client
    hidden = resource(user, source=source)
    visible = resource(user)
    assert_catalog_boundary(client, hidden, visible)


@pytest.mark.parametrize(
    "code",
    [
        "demo-geology-rules",
        "real-geology-age-rules",
        "geology-review-rules",
        "geology-review-expanded-20261025-rules",
        "geology-multi-rules",
        "geology-multi-rules-complete-20261025",
        "geology-multi-rules-complete-20261106",
        "geology-review-new-area-rules",
    ],
)
def test_registered_rule_codes_are_hidden_even_with_business_source(
    catalog_client, code
):
    client, user = catalog_client
    hidden = resource(user, code=code)
    visible = resource(user)
    assert_catalog_boundary(client, hidden, visible)


@pytest.mark.parametrize(
    "source,code",
    [
        ("", "ordinary-test-demo"),
        ("用户导入", "geology-review-field-observations"),
        ("geology-review-input:case", "geology-review-lithology"),
        ("geology-multi-input:case", "geology-multi-lithology"),
        ("compute-output:actual-output", "ordinary-compute-result"),
        ("workflow-report:completed-workflow", "ordinary-workflow-report"),
    ],
)
def test_business_uploads_and_real_results_keep_their_catalog_entries(
    catalog_client, source, code
):
    client, user = catalog_client
    visible = resource(user, source=source, code=code)
    hidden = resource(user, source="geology-multi-frozen-rules:workflow")
    assert_catalog_boundary(client, hidden, visible)


def test_public_catalogs_also_hide_internal_packets_without_hiding_unbound_layers(
    client,
):
    hidden = resource(None, source="demo-changes:workflow")
    visible = resource(None, name="公开 test 演示业务资料")
    unbound = MapLayer.objects.create(
        name="默认底图", code="unbound-default", layer_type="raster", is_active=True
    )
    response = client.get("/api/catalog/resources/", HTTP_X_PROJECT_ID="1")
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert hidden[0].id not in ids and visible[0].id in ids
    response = client.get("/api/layers/", HTTP_X_PROJECT_ID="1")
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert hidden[1].id not in ids and {visible[1].id, unbound.id} <= ids
