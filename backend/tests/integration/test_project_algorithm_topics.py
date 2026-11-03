import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.compute.models import AlgorithmCategory, AlgorithmResource
from apps.compute.services import allowed_algorithms
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import Project


@pytest.mark.django_db
@pytest.mark.parametrize("geology_code", ["02", "demo-geology-reasoning"])
def test_project_topics_filter_shared_tools_but_keep_local_and_history(geology_code):
    user = get_user_model().objects.create_superuser("topic-admin", password="test")
    geology = Project.objects.create(name="地质", code=geology_code)
    ecology = Project.objects.create(name="生态", code="demo-arid-ecology")
    with project_scope(ProjectScope((1,), 1, user.id, True)):
        for identifier, category in [
            ("raster-ndwi", "水体指数"),
            ("geology-map-check", "地质检查"),
            ("vector-metrics", "矢量统计"),
        ]:
            AlgorithmResource.objects.create(
                identifier=identifier,
                name=identifier,
                category=category,
                created_by=user,
            )
            AlgorithmCategory.objects.create(name=category)
    with project_scope(ProjectScope((geology.id,), geology.id, user.id, True)):
        AlgorithmResource.objects.create(
            identifier="local-operator", name="本项目工具", created_by=user
        )
        assert set(allowed_algorithms().values_list("identifier", flat=True)) == {
            "geology-map-check",
            "vector-metrics",
            "local-operator",
        }
    with project_scope(ProjectScope((ecology.id,), ecology.id, user.id, True)):
        assert set(allowed_algorithms().values_list("identifier", flat=True)) == {
            "raster-ndwi",
            "vector-metrics",
        }
    client = Client()
    client.force_login(user)
    response = client.get("/api/compute/categories/", HTTP_X_PROJECT_ID=str(geology.id))
    assert response.status_code == 200
    assert {row["name"] for row in response.json()["items"]} == {"地质检查", "矢量统计"}
    assert AlgorithmResource._base_manager.count() == 4
