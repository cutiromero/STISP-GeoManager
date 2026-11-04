import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission

from apps.catalog.models import (
    DataResource,
    WorkspaceScene,
    ResultArtifact,
    MapComposition,
    DictionaryItem,
)
from apps.catalog.permissions import user_can_access
from apps.content.models import Article
from apps.projects.models import Project, ProjectMembership

pytestmark = pytest.mark.django_db


@pytest.fixture
def team():
    users = get_user_model()
    admin = users.objects.create_superuser("label-admin", password="test-pass")
    member = users.objects.create_user("label-member", password="test-pass")
    outsider = users.objects.create_user("label-outsider", password="test-pass")
    role = Group.objects.create(name="Same research role")
    role.permissions.add(
        *Permission.objects.filter(
            codename__in=[
                "browse_data",
                "query_data",
                "view_workspacescene",
                "view_mapcomposition",
                "view_resultartifact",
                "download_resultartifact",
                "export_dataresource",
            ]
        )
    )
    member.groups.add(role)
    outsider.groups.add(role)
    a = Project.objects.create(name="项目甲", code="review-a")
    b = Project.objects.create(name="项目乙", code="review-b")
    ProjectMembership.objects.create(user=member, project=a)
    ProjectMembership.objects.create(user=member, project=b)
    return admin, member, outsider, a, b


def test_tag_members_read_project_data_but_keep_workspaces_private(
    client, team, tmp_path, monkeypatch
):
    admin, member, outsider, a, b = team
    resource = DataResource.objects.create(
        project_tag=a,
        name="成员数据",
        code="review-table",
        data_type="table",
        maintainer=admin,
    )
    scene = WorkspaceScene.objects.create(
        project_tag=a, owner=admin, name="成员工程", kind="project"
    )
    composition = MapComposition.objects.create(
        project_tag=a, owner=admin, project=scene, name="成员出图", status="published"
    )
    artifact = ResultArtifact.objects.create(
        project_tag=a,
        owner=admin,
        name="成员成果",
        status="published",
        source_type="imported",
        result_type="table",
        file_name="result.csv",
        file_path="result.csv",
        category=DictionaryItem.objects.get(
            dict_type="data_category", code="non_spatial"
        ),
        mime_type="text/csv",
    )
    (tmp_path / "result.csv").write_text("value\n1\n", encoding="utf-8")
    monkeypatch.setattr(
        "apps.catalog.results.app_path", lambda *parts: tmp_path.joinpath(*parts)
    )
    headers = {"HTTP_X_PROJECT_ID": str(a.id)}
    client.force_login(member)
    for url, expected in [
        ("/api/catalog/resources/", resource.id),
        ("/api/catalog/map-compositions/", composition.id),
        ("/api/catalog/results/", artifact.id),
    ]:
        response = client.get(url, **headers)
        assert response.status_code == 200, (url, response.content)
        assert expected in {item["id"] for item in response.json()["items"]}
    assert client.get("/api/catalog/workspaces/", **headers).json()["items"] == []
    assert (
        client.get(f"/api/catalog/workspaces/{scene.id}/", **headers).status_code == 404
    )
    file_url = f"/api/catalog/results/{artifact.id}/file/?variant=artifact"
    response = client.get(file_url, **headers)
    assert response.status_code == 200
    assert b"value" in b"".join(response.streaming_content)
    assert user_can_access(resource, member)
    assert not user_can_access(resource, outsider)
    # A member of another selected project cannot address this object's ID.
    assert client.get(file_url, HTTP_X_PROJECT_ID=str(b.id)).status_code == 404
    client.force_login(outsider)
    assert client.get(file_url, **headers).status_code == 404
    assert (
        client.get(f"/api/catalog/workspaces/{scene.id}/", **headers).status_code == 404
    )
    assert (
        client.get("/api/catalog/resources/", HTTP_X_PROJECT_ID="1").json()["items"]
        == []
    )
    client.force_login(admin)
    assert client.get(file_url, **headers).status_code == 200
    # Revocation applies to downloads immediately, not only after re-login.
    ProjectMembership.objects.filter(user=member, project=a).delete()
    client.force_login(member)
    assert client.get(file_url, **headers).status_code == 404


def test_owner_only_resource_is_hidden_from_project_members(client, team):
    admin, member, _outsider, a, _b = team
    resource = DataResource.objects.create(
        project_tag=a,
        name="个人数据",
        code="owner-only-table",
        data_type="table",
        maintainer=admin,
        owner_only=True,
    )
    headers = {"HTTP_X_PROJECT_ID": str(a.id)}

    client.force_login(member)
    response = client.get("/api/catalog/resources/", **headers)
    assert response.status_code == 200
    assert resource.id not in {item["id"] for item in response.json()["items"]}
    assert not user_can_access(resource, member)

    client.force_login(admin)
    assert user_can_access(resource, admin)
    response = client.get("/api/catalog/resources/", **headers)
    assert resource.id in {item["id"] for item in response.json()["items"]}


def test_new_account_default_and_only_superadmin_can_assign(client, team):
    admin, member, outsider, a, b = team
    client.force_login(outsider)
    assert [p["id"] for p in client.get("/api/projects/").json()["items"]] == [1]
    outsider.user_permissions.add(
        Permission.objects.get(content_type__app_label="core", codename="manage_auth")
    )
    url = f"/api/projects/assignments/{member.id}/"
    assert (
        client.post(
            url, {"projectIds": [a.id]}, content_type="application/json"
        ).status_code
        == 403
    )
    client.force_login(admin)
    assert (
        client.post(
            url, {"projectIds": [a.id, b.id]}, content_type="application/json"
        ).status_code
        == 200
    )
    assert set(
        ProjectMembership.objects.filter(user=member).values_list(
            "project_id", flat=True
        )
    ) == {a.id, b.id}


def test_knowledge_and_news_are_public_across_project_choices(client, team):
    admin, member, _, a, b = team
    article = Article.objects.create(
        kind="knowledge", title="公共知识", category="遥感基础", status="published"
    )
    news = Article.objects.create(
        kind="news",
        title="公共新闻",
        category="学术会议",
        status="published",
    )
    for user in (None, member, admin):
        client.logout()
        if user:
            client.force_login(user)
        response = client.get(
            "/api/content/articles/?kind=knowledge", HTTP_X_PROJECT_ID="1"
        )
        assert [i["id"] for i in response.json()["items"]] == [article.id]
        for project_id in (1, a.id, b.id):
            assert [
                i["id"]
                for i in client.get(
                    "/api/content/articles/?kind=news",
                    HTTP_X_PROJECT_ID=str(project_id),
                ).json()["items"]
            ] == [news.id]
    invalid = client.post(
        "/api/content/articles/",
        {"kind": "knowledge", "title": "误建私有科普", "category": "遥感基础"},
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(b.id),
    )
    assert invalid.status_code == 201
    assert invalid.json()["projectTagId"] == 1


def test_resource_classification_uses_coordinate_information(client, team):
    from apps.catalog.serializers import serialize_resource

    admin, _, _, _, _ = team
    geo = DataResource.objects.create(
        name="坐标数据", code="geo", data_type="vector", coordinate_system="EPSG:4326"
    )
    no_geo = DataResource.objects.create(
        name="无坐标影像", code="no-geo", data_type="raster"
    )
    table = DataResource.objects.create(
        name="属性数据", code="plain", data_type="table"
    )
    assert geo.category.code == geo.spatial_class == "spatial"
    assert no_geo.category.code == table.category.code == "non_spatial"
    assert serialize_resource(no_geo)["defaultView"] == "metadata"
    assert serialize_resource(table)["defaultView"] == "table"
    client.force_login(admin)
    for param in ("spatialClass", "categoryCode"):
        assert [
            i["id"]
            for i in client.get("/api/catalog/resources/", {param: "spatial"}).json()[
                "items"
            ]
        ] == [geo.id]
        assert {
            i["id"]
            for i in client.get(
                "/api/catalog/resources/", {param: "non_spatial"}
            ).json()["items"]
        } == {no_geo.id, table.id}
