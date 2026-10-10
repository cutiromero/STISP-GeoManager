import json
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.knowledge.models import KnowledgeEntry, KnowledgeRevision
from apps.knowledge.services import search_entries
from apps.projects.models import Project


BATCH = "knowledge-zones-20261010"


def seed(**options):
    stream = StringIO()
    call_command("seed_geology_knowledge", batch=BATCH, stdout=stream, **options)
    return json.loads(stream.getvalue())


def test_domain_seed_retains_existing_knowledge_and_is_idempotent(db):
    Project.objects.get_or_create(
        pk=1, defaults={"name": "公开", "code": "default", "is_default": True}
    )
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
    for domain in ("remote_sensing", "pipelines", "geology", "arid_ecology"):
        assert (
            KnowledgeEntry.objects.filter(domain=domain, status="published").count()
            == 10
        )


def test_new_ndvi_and_pipeline_sources_are_retrievable_in_their_domains(db):
    Project.objects.get_or_create(
        pk=1, defaults={"name": "公开", "code": "default", "is_default": True}
    )
    seed()
    user = get_user_model().objects.create_user(username="zones-seed-reader")
    for domain, query, expected in (
        ("remote_sensing", "NDVI", "NDVI 用红光与近红外反射率表达植被光谱差异"),
        ("arid_ecology", "NDVI", "NDVI距平可用于识别偏离常年的植被状态"),
        ("pipelines", "地质灾害", "地面运动、洪水及外力应纳入管道风险分析"),
        ("geology", "布尔", "蚀变类型可由可见近红外与短波红外矿物证据组合推断"),
    ):
        result = search_entries(user, query, domains=[domain], limit=50)
        assert expected in {entry["title"] for entry in result["items"]}
        assert all(entry["domain"] == domain for entry in result["items"])
        assert all(
            entry["sources"] and entry["conditions"] for entry in result["items"]
        )


def test_seed_source_locators_and_keys_are_complete():
    path = Path(__file__).parents[2] / "apps/knowledge/seed_entries_20261010.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
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
