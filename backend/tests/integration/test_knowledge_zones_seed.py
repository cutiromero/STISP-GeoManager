import json
from io import StringIO
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client

from apps.knowledge.models import KnowledgeEntry, KnowledgeRevision
from apps.knowledge.services import serialize, validate_entry
from apps.projects.models import Project, ProjectMembership


BATCH = "knowledge-zones-20261010"


def seed(**options):
    stream = StringIO()
    call_command("seed_geology_knowledge", batch=BATCH, stdout=stream, **options)
    return json.loads(stream.getvalue())


@pytest.fixture
def projects(db):
    public, _ = Project.objects.get_or_create(
        pk=1, defaults={"name": "公开", "code": "default", "is_default": True}
    )
    return {
        "remote_sensing": public,
        "pipelines": Project.objects.create(name="管道", code="gd"),
        "geology": Project.objects.create(name="地质", code="02"),
        "arid_ecology": Project.objects.create(name="生态", code="demo-arid-ecology"),
    }


def test_domain_seed_retains_existing_knowledge_and_is_idempotent(projects):
    existing = KnowledgeEntry.objects.create(
        title="人工修订内容",
        statement="保留原有证据",
        domain="pipelines",
        category="人工知识",
        revision=9,
        status="retired",
        seed_key="existing-manual",
    )
    original = KnowledgeEntry.objects.filter(pk=existing.pk).values().get()
    assert seed(dry_run=True)["created"] == 40
    assert KnowledgeEntry.objects.count() == 1
    assert seed()["created"] == 40
    assert seed()["created"] == 0
    assert KnowledgeEntry.objects.filter(pk=existing.pk).values().get() == original
    assert KnowledgeRevision.objects.count() == 40
    for domain, project in projects.items():
        assert (
            KnowledgeEntry.objects.filter(
                domain=domain, project_tag=project, status="published"
            ).count()
            == 10
        )


def test_existing_public_seeds_move_without_losing_edits_and_follow_project_acl(
    projects,
):
    records = load_seeds()
    original = {}
    for domain in projects:
        item = next(item for item in records if item["domain"] == domain)
        data = validate_entry({k: v for k, v in item.items() if k != "seedKey"})
        entry = KnowledgeEntry.objects.create(
            seed_key=item["seedKey"],
            **{**data, "title": f"人工修订-{domain}"},
            revision=2,
        )
        revision = KnowledgeRevision.objects.create(
            entry=entry, revision=2, snapshot=serialize(entry)
        )
        original[domain] = (entry, revision)

    def reassign(**options):
        return seed(reassign_existing=True, **options)

    assert reassign(dry_run=True)["moved"] == 3
    assert KnowledgeEntry.objects.filter(project_tag_id=1).count() == 4
    assert reassign()["moved"] == 3
    assert reassign()["moved"] == 0
    assert KnowledgeEntry.objects.count() == KnowledgeRevision.objects.count() == 4
    user = get_user_model().objects.create_user(username="zones-seed-reader")
    client = Client()
    client.force_login(user)
    for domain, project in projects.items():
        if project.pk != 1:
            ProjectMembership.objects.create(project=project, user=user)
    for domain, project in projects.items():
        entry, revision = original[domain]
        title = entry.title
        snapshot = revision.snapshot
        entry.refresh_from_db()
        revision.refresh_from_db()
        assert entry.title == title and entry.revision == 2
        assert entry.project_tag_id == revision.project_tag_id == project.pk
        assert revision.snapshot == {**snapshot, "projectTagId": project.pk}
        headers = {"HTTP_X_PROJECT_ID": str(project.pk)}
        result = client.get("/api/knowledge/entries/", **headers).json()
        assert {item["id"] for item in result["items"]} == {
            entry.pk,
            original["remote_sensing"][0].pk,
        }
        for other in projects.keys() - {domain, "remote_sensing"}:
            other_id = original[other][0].pk
            assert (
                client.get(f"/api/knowledge/entries/{other_id}/", **headers).status_code
                == 404
            )


def test_seed_aborts_instead_of_falling_back_to_public(projects):
    project = projects["pipelines"]
    project.is_active = False
    project.save(update_fields=["is_active"])
    with pytest.raises(CommandError, match="gd"):
        seed()
    assert not KnowledgeEntry.objects.exists()


def load_seeds():
    path = Path(__file__).parents[2] / "apps/knowledge/seed_entries_20261010.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_seed_source_locators_and_keys_are_complete():
    entries = load_seeds()
    assert len({entry["seedKey"] for entry in entries}) == 40
    for entry in entries:
        assert entry["conditions"] and entry["exceptions"]
        assert entry["ruleKind"] == "none"
        assert all(
            source["url"].startswith("https://")
            and source["locator"]
            and source["excerpt"]
            for source in entry["sources"]
        )
