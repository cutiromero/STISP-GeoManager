from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from apps.core.initialization import (
    ensure_superadmin_defaults,
    DEFAULT_USER_GROUP_NAME,
    RESEARCH_USER_GROUP_NAME,
    SUPERADMIN_GROUP_NAME,
    PLATFORM_ADMIN_GROUP_NAME,
)
from apps.core.models import RoleApplication


def users():
    ensure_superadmin_defaults(create_account=False)
    User = get_user_model()
    normal = User.objects.create_user(
        "access-normal", password="testpass", email="normal@example.org"
    )
    normal.groups.add(Group.objects.get(name=DEFAULT_USER_GROUP_NAME))
    admin = User.objects.create_user("access-admin", password="testpass")
    admin.groups.add(Group.objects.get(name=SUPERADMIN_GROUP_NAME))
    return normal, admin


def test_own_permissions_and_research_application_lifecycle(client):
    normal, admin = users()
    client.force_login(normal)
    before = client.get("/api/auth/access/").json()
    own = {p["id"] for p in before["permissions"]}
    assert "core.manage_auth" not in own
    assert before["researchEligible"] and before["application"] is None
    assert {p["id"] for p in before["researchAdditionalPermissions"]}.isdisjoint(own)
    profile = client.get("/api/admin/profile/").json()
    assert all(
        p["id"] in profile["effectivePermissions"]
        for p in profile["availablePermissions"]
    )
    body = dict(displayName="申请人", department="研究组", reason="需要上传数据并分析")
    response = client.post(
        "/api/auth/research-application/", body, content_type="application/json"
    )
    assert response.status_code == 200
    app = response.json()["application"]
    assert app["status"] == "pending"
    assert not normal.groups.filter(name=RESEARCH_USER_GROUP_NAME).exists()
    assert (
        client.post(
            "/api/auth/research-application/", body, content_type="application/json"
        ).status_code
        == 409
    )
    client.force_login(admin)
    listed = client.get("/api/admin/role-applications/").json()["items"]
    assert any(item["id"] == app["id"] for item in listed)
    url = f"/api/admin/role-applications/{app['id']}/review/"
    assert (
        client.post(
            url,
            dict(action="reject", reviewNote="补充研究计划"),
            content_type="application/json",
        ).status_code
        == 200
    )
    client.force_login(normal)
    assert (
        client.get("/api/auth/access/").json()["application"]["reviewNote"]
        == "补充研究计划"
    )
    assert (
        client.post(
            "/api/auth/research-application/", body, content_type="application/json"
        ).status_code
        == 200
    )
    client.force_login(admin)
    assert (
        client.post(
            url, dict(action="approve"), content_type="application/json"
        ).status_code
        == 200
    )
    client.force_login(normal)
    after = client.get("/api/auth/access/").json()
    assert (
        not after["researchEligible"] and after["application"]["status"] == "approved"
    )
    assert normal.groups.filter(name=RESEARCH_USER_GROUP_NAME).exists()
    assert not normal.groups.filter(name=DEFAULT_USER_GROUP_NAME).exists()


def test_applications_are_private_and_superadmin_review_only(client):
    normal, _ = users()
    app = RoleApplication.objects.create(user=normal, reason="private request")
    assert client.get("/api/auth/access/").status_code == 401
    other = get_user_model().objects.create_user("access-other", password="testpass")
    other.groups.add(Group.objects.get(name=PLATFORM_ADMIN_GROUP_NAME))
    client.force_login(other)
    assert client.get("/api/auth/access/").json()["application"] is None
    assert client.get("/api/admin/role-applications/").status_code == 403
    assert (
        client.post(
            f"/api/admin/role-applications/{app.id}/review/",
            dict(action="approve"),
            content_type="application/json",
        ).status_code
        == 403
    )
    client.logout()
    client.post("/api/auth/guest-login/")
    assert not client.get("/api/auth/access/").json()["researchEligible"]
    assert (
        client.post(
            "/api/auth/research-application/",
            dict(displayName="x", department="x", reason="x"),
            content_type="application/json",
        ).status_code
        == 403
    )


def test_english_search_preserves_canonical_algorithm_fields(client):
    from apps.compute.models import AlgorithmResource, AlgorithmVersion

    owner = get_user_model().objects.create_user("algorithm-author")
    a = AlgorithmResource.objects.create(
        identifier="mhgdal-polygonize", name="栅格矢量化", created_by=owner
    )
    AlgorithmVersion.objects.create(
        algorithm=a,
        version="1.0.0",
        status="published",
        manifest={"identifier": "mhgdal-polygonize"},
        checksum="test",
        package_path="test.zip",
    )
    response = client.get("/api/compute/algorithms/?q=polygonization")
    assert response.status_code == 200
    assert response.json()["items"][0]["name"] == "栅格矢量化"
