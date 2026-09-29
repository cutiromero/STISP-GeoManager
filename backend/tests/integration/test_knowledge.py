import json

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client

from apps.knowledge.models import KnowledgeEntry, KnowledgeRevision
from apps.knowledge.services import search_entries
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import Project, ProjectMembership


def payload(**overrides):
    return {
        "title": "霞石与石英的平衡关系",
        "category": "矿物平衡",
        "subject": "霞石",
        "predicate": "平衡约束",
        "object": "石英",
        "statement": "在指定平衡体系内检验组合。",
        "explanation": "保留原始观测。",
        "conditions": ["同阶段平衡"],
        "exceptions": ["非平衡残晶"],
        "aliases": ["nepheline"],
        "sources": [
            {
                "title": "矿物学",
                "url": "https://example.org/minerals",
                "locator": "第7章",
                "excerpt": "相平衡",
            }
        ],
        "status": "published",
        "ruleKind": "mineral_equilibrium",
        "ruleConfig": {
            "minerals": ["霞石", "石英"],
            "system": "silica_undersaturated_equilibrium_igneous",
        },
        **overrides,
    }


@pytest.fixture
def users(db):
    model = get_user_model()
    admin = model.objects.create_superuser(
        "knowledge-admin", password="test-password-only"
    )
    reader = model.objects.create_user(
        "knowledge-reader", password="test-password-only"
    )
    Project.objects.get_or_create(
        pk=1, defaults={"name": "公开", "code": "default", "is_default": True}
    )
    private = Project.objects.create(name="知识研究", code="knowledge-private")
    ProjectMembership.objects.create(project=private, user=reader)
    client = Client()
    client.force_login(admin)
    return client, admin, reader, private


def create(client, project=1, **overrides):
    return client.post(
        "/api/knowledge/entries/",
        json.dumps(payload(**overrides)),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(project),
    )


def test_project_visibility_drafts_and_public_reuse(users):
    client, admin, reader, private = users
    public = create(client).json()
    secret = create(client, private.id, title="私有知识").json()
    draft = create(client, private.id, title="草稿知识", status="draft").json()
    client.force_login(reader)
    result = client.get(
        "/api/knowledge/entries/", HTTP_X_PROJECT_ID=str(private.id)
    ).json()
    assert {v["id"] for v in result["items"]} == {public["id"], secret["id"]}
    assert not result["canEdit"]
    assert (
        client.get(
            f"/api/knowledge/entries/{draft['id']}/", HTTP_X_PROJECT_ID=str(private.id)
        ).status_code
        == 404
    )
    result = client.get("/api/knowledge/entries/", HTTP_X_PROJECT_ID="1").json()
    assert [v["id"] for v in result["items"]] == [public["id"]]
    ProjectMembership.objects.filter(user=reader, project=private).delete()
    with project_scope(ProjectScope((private.id,), private.id, user_id=reader.id)):
        from django.core.exceptions import PermissionDenied

        with pytest.raises(PermissionDenied):
            search_entries(reader)


def test_edit_auth_revision_and_source_validation(users):
    client, admin, reader, private = users
    entry = create(client).json()
    client.force_login(reader)
    assert create(client).status_code == 403
    client.force_login(admin)
    url = f"/api/knowledge/entries/{entry['id']}/"
    edited = client.patch(
        url,
        json.dumps(payload(revision=1, title="修订知识")),
        content_type="application/json",
        HTTP_X_PROJECT_ID="1",
    )
    assert edited.status_code == 200
    assert edited.json()["revision"] == 2
    assert KnowledgeRevision.objects.filter(entry_id=entry["id"]).count() == 2
    assert (
        client.patch(
            url,
            json.dumps(payload(revision=1)),
            content_type="application/json",
            HTTP_X_PROJECT_ID="1",
        ).status_code
        == 409
    )
    assert create(client, sources=[]).status_code == 400
    assert (
        create(
            client,
            sources=[
                {
                    "title": "x",
                    "url": "javascript:alert(1)",
                    "locator": "",
                    "excerpt": "",
                }
            ],
        ).status_code
        == 400
    )
    assert create(client, ruleConfig={"code": "arbitrary"}).status_code == 400


def test_condition_rules_never_infer_equilibrium(users):
    client, _, _, _ = users
    entry = create(client).json()
    url = "/api/knowledge/check/"

    def check(facts):
        result = client.post(
            url,
            json.dumps({"facts": facts, "entryIds": [entry["id"]]}),
            content_type="application/json",
            HTTP_X_PROJECT_ID="1",
        )
        assert result.status_code == 200, result.content
        return result.json()["findings"][0]["status"]

    assert check({}) == "needs_context"
    assert check({"minerals": ["霞石", "石英"]}) == "needs_context"
    facts = {
        "minerals": ["霞石", "石英"],
        "equilibrium": True,
        "system": "silica_undersaturated_equilibrium_igneous",
    }
    assert check(facts) == "conflict"
    assert check({**facts, "minerals": ["霞石", "辉石"]}) == "pass"
    assert check({**facts, "equilibrium": "true"}) == "needs_context"


def test_search_aliases_and_long_questions(users):
    client, admin, _, _ = users
    entry = create(client).json()
    assert search_entries(admin, "nepheline")["items"][0]["id"] == entry["id"]
    assert (
        search_entries(admin, "请帮我核查石英和霞石能不能共生")["items"][0]["id"]
        == entry["id"]
    )
    assert search_entries(admin, "未知的海洋观测")["total"] == 0


def test_seed_preserves_manual_changes_and_is_repeatable(users):
    call_command("seed_geology_knowledge")
    count = KnowledgeEntry.objects.count()
    assert count >= 15
    entry = KnowledgeEntry.objects.first()
    entry.title = "人工补充保留"
    entry.save()
    call_command("seed_geology_knowledge")
    assert KnowledgeEntry.objects.count() == count
    entry.refresh_from_db()
    assert entry.title == "人工补充保留"


def test_anonymous_and_bad_inputs(users):
    client, *_ = users
    assert client.get("/api/knowledge/entries/?limit=999").status_code == 400
    assert (
        client.post(
            "/api/knowledge/check/", '{"facts":null}', content_type="application/json"
        ).status_code
        == 400
    )
    client.logout()
    assert client.get("/api/knowledge/entries/").status_code == 401


def test_rule_normalization_and_large_or_nested_values(users):
    client, *_ = users
    duplicate = {"minerals": ["霞石", " 霞石 "], "system": "igneous"}
    assert create(client, ruleConfig=duplicate).status_code == 400
    good = {"minerals": [" 霞石 ", "石英"], "system": " igneous "}
    response = create(client, ruleConfig=good)
    assert response.status_code == 200
    entry = response.json()
    assert entry["ruleConfig"]["minerals"] == ["霞石", "石英"]
    response = client.post(
        "/api/knowledge/check/",
        json.dumps(
            {
                "entryIds": [entry["id"]],
                "facts": {
                    "minerals": ["霞石", "石英"],
                    "equilibrium": True,
                    "system": "igneous",
                },
            }
        ),
        content_type="application/json",
    )
    assert response.json()["findings"][0]["status"] == "conflict"
    assert (
        create(
            client,
            ruleKind="numeric_range",
            ruleConfig={"field": "x", "minimum": 0, "maximum": 10**400},
        ).status_code
        == 400
    )
    nested = '{"facts":' + "[" * 1100 + "0" + "]" * 1100 + "}"
    assert (
        client.post(
            "/api/knowledge/check/", nested, content_type="application/json"
        ).status_code
        == 400
    )
