import json
from collections import Counter
from io import StringIO
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.knowledge.models import (
    KnowledgeDocument,
    KnowledgeEntry,
    KnowledgeLibrary,
    KnowledgeRevision,
)
from apps.knowledge.services import search_entries, validate_entry
from apps.projects.context import ProjectScope, current_scope, project_scope
from apps.projects.models import Project, ProjectMembership


SEED_DIRECTORY = Path(__file__).parents[2] / "apps/knowledge"
BATCH = "geology-20261009"


def seeds(filename):
    return json.loads((SEED_DIRECTORY / filename).read_text(encoding="utf-8"))


def run_seed(**options):
    output = StringIO()
    call_command("seed_geology_knowledge", stdout=output, **options)
    return json.loads(output.getvalue())


@pytest.fixture
def geology_project(db):
    Project.objects.get_or_create(
        pk=1, defaults={"name": "公开", "code": "default", "is_default": True}
    )
    return Project.objects.create(name="核地院逻辑推理", code="02")


def test_expansion_contains_thirty_sourced_conditional_entries():
    base = seeds("seed_entries.json")
    additions = seeds("seed_entries_20261009.json")
    keys = {entry["seedKey"] for entry in additions}
    assert len(additions) == len(keys) == 30
    assert not keys.intersection(entry["seedKey"] for entry in base)
    assert Counter(entry["category"] for entry in additions) == {
        "成矿与蚀变": 21,
        "地层与构造": 3,
        "数据质量": 2,
        "遥感判读": 1,
        "矿物平衡": 3,
    }
    for entry in additions:
        clean = validate_entry({k: v for k, v in entry.items() if k != "seedKey"})
        assert clean["status"] == "published"
        assert clean["rule_kind"] == "none"
        assert clean["rule_config"] == {}
        assert clean["conditions"] and clean["exceptions"]
        assert all(
            source[field]
            for source in clean["sources"]
            for field in ("title", "url", "locator", "excerpt")
        )


def test_default_batch_preserves_original_twenty_entry_scope(geology_project):
    result = run_seed()
    assert result == {
        "batch": "base",
        "dryRun": False,
        "created": 20,
        "preserved": 0,
        "moved": 0,
    }
    assert set(KnowledgeEntry.objects.values_list("seed_key", flat=True)) == {
        entry["seedKey"] for entry in seeds("seed_entries.json")
    }
    assert KnowledgeRevision.objects.count() == 20


def test_expansion_dry_run_and_independent_batch(geology_project):
    assert run_seed(batch=BATCH, dry_run=True) == {
        "batch": BATCH,
        "dryRun": True,
        "created": 30,
        "preserved": 0,
        "moved": 0,
    }
    assert KnowledgeEntry.objects.count() == KnowledgeRevision.objects.count() == 0
    assert run_seed(batch=BATCH)["created"] == 30
    assert KnowledgeEntry.objects.count() == KnowledgeRevision.objects.count() == 30
    assert set(KnowledgeEntry.objects.values_list("seed_key", flat=True)) == {
        entry["seedKey"] for entry in seeds("seed_entries_20261009.json")
    }
    assert KnowledgeDocument.objects.count() == KnowledgeLibrary.objects.count() == 0


def test_expansion_only_appends_and_keeps_all_manual_fields(geology_project):
    run_seed()
    original = KnowledgeEntry.objects.first()
    original.title = "已有知识的人工标题"
    original.statement = "已有知识经人工修订，导入时应完整保留。"
    original.status = "retired"
    original.revision = 7
    original.save()
    old_entries = list(KnowledgeEntry.objects.order_by("id").values())
    old_versions = list(KnowledgeRevision.objects.order_by("id").values())
    old_ids = [entry["id"] for entry in old_entries]

    assert run_seed(batch=BATCH)["created"] == 30
    assert KnowledgeEntry.objects.count() == KnowledgeRevision.objects.count() == 50
    assert (
        list(KnowledgeEntry.objects.filter(pk__in=old_ids).order_by("id").values())
        == old_entries
    )
    assert (
        list(
            KnowledgeRevision.objects.filter(entry_id__in=old_ids)
            .order_by("id")
            .values()
        )
        == old_versions
    )
    additions = KnowledgeEntry.objects.exclude(pk__in=old_ids)
    assert set(additions.values_list("project_tag_id", flat=True)) == {
        geology_project.pk
    }
    for entry in additions:
        version = entry.versions.get()
        assert version.revision == entry.revision == 1
        assert (
            version.project_tag_id
            == version.snapshot["projectTagId"]
            == geology_project.pk
        )
        assert version.snapshot["title"] == entry.title

    addition = additions.first()
    addition.title = "新增知识后续人工修订"
    addition.conditions = ["人工补充适用条件"]
    addition.save()
    all_entries = list(KnowledgeEntry.objects.order_by("id").values())
    all_versions = list(KnowledgeRevision.objects.order_by("id").values())
    assert run_seed(batch=BATCH) == {
        "batch": BATCH,
        "dryRun": False,
        "created": 0,
        "preserved": 30,
        "moved": 0,
    }
    assert run_seed(batch=BATCH, dry_run=True)["created"] == 0
    assert list(KnowledgeEntry.objects.order_by("id").values()) == all_entries
    assert list(KnowledgeRevision.objects.order_by("id").values()) == all_versions
    assert KnowledgeDocument.objects.count() == KnowledgeLibrary.objects.count() == 0


def test_expansion_writes_geology_project_even_with_private_active_scope(
    geology_project,
):
    private = Project.objects.create(name="临时隔离测试", code="seed-expansion-private")
    seed = seeds("seed_entries_20261009.json")[0]
    data = validate_entry({k: v for k, v in seed.items() if k != "seedKey"})
    scope = ProjectScope((private.pk,), private.pk, superadmin=True)
    with project_scope(scope):
        entry = KnowledgeEntry.objects.create(seed_key=seed["seedKey"], **data)
        entry.title = "私有项目同标识知识"
        entry.save()
        before = list(KnowledgeEntry.objects.values())
        assert run_seed(batch=BATCH)["created"] == 30
        assert current_scope.get() == scope
        assert list(KnowledgeEntry.objects.values()) == before
        assert KnowledgeRevision.objects.count() == 0
    assert (
        KnowledgeEntry.objects.filter(project_tag_id=geology_project.pk).count() == 30
    )
    assert (
        KnowledgeRevision.objects.filter(project_tag_id=geology_project.pk).count()
        == 30
    )


@pytest.mark.parametrize(
    ("query", "seed_key"),
    [
        ("白榴石石英共生", "leucite-quartz-equilibrium"),
        ("corundum", "corundum-quartz-equilibrium-domain"),
        ("请解释古地下水位与蒸汽加热蚀变的关系", "epithermal-steam-heated-overprint"),
        ("Mississippi Valley", "mvt-carbonate-platform-hosts"),
    ],
)
def test_expansion_is_retrievable_with_sources(geology_project, query, seed_key):
    run_seed(batch=BATCH)
    user = get_user_model().objects.create_user("seed-reader")
    assert search_entries(user, query)["total"] == 0
    ProjectMembership.objects.create(project=geology_project, user=user)
    with project_scope(
        ProjectScope((geology_project.pk,), geology_project.pk, user.pk)
    ):
        result = search_entries(user, query, limit=30)
    expected_id = KnowledgeEntry.objects.get(seed_key=seed_key).id
    assert expected_id in {entry["id"] for entry in result["items"]}
    match = next(entry for entry in result["items"] if entry["id"] == expected_id)
    assert match["sources"][0]["url"].startswith("https://")
    assert match["conditions"] and match["exceptions"]
