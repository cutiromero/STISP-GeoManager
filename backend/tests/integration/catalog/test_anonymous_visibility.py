import pytest
from django.contrib.auth.models import AnonymousUser

from apps.catalog.models import DataResource
from apps.catalog.permissions import related_access_filter, user_can_access
from apps.projects.models import Project


@pytest.mark.django_db
def test_anonymous_catalog_only_lists_active_public_resources(client):
    private = Project.objects.create(name="私有测试", code="anon-private")
    visible = DataResource.objects.create(
        name="公开", code="anon-public", data_type="table"
    )
    hidden = [
        DataResource.objects.create(
            name="个人", code="anon-owner", data_type="table", owner_only=True
        ),
        DataResource.objects.create(
            name="停用", code="anon-inactive", data_type="table", status="inactive"
        ),
        DataResource.objects.create(
            name="私有", code="anon-private", data_type="table", project_tag=private
        ),
    ]
    response = client.get("/api/catalog/resources/", HTTP_X_PROJECT_ID="1")
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert visible.id in ids
    assert not ids.intersection(item.id for item in hidden)
    assert not user_can_access(hidden[0], AnonymousUser())
    # Query compilation must never try to coerce AnonymousUser to an integer.
    from apps.catalog.models import MapLayer

    list(
        MapLayer.objects.filter(related_access_filter(AnonymousUser(), "data_resource"))
    )
