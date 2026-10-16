import copy
import hashlib
import json
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.audit.models import OperationLog
from apps.knowledge import library
from apps.knowledge.models import KnowledgeDocument, KnowledgeEntry, KnowledgeRevision
from apps.knowledge.services import search_entries
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import Project, ProjectMembership


@pytest.fixture
def ecology_import(tmp_path, settings, monkeypatch):
    project = Project.objects.create(name="干旱区生态", code="ecology-import-test")
    user = get_user_model().objects.create_superuser(
        "ecology-importer", password="test"
    )
    settings.PROJECT_CONFIG = SimpleNamespace(app_path=lambda *p: tmp_path.joinpath(*p))
    engine = Mock()
    engine.list_knowledge_bases.return_value = []
    engine.create_knowledge_base.return_value = {"id": "ecology-only-kb"}
    engine.upload_file.return_value = {"id": "reviewed-doc", "parse_status": "pending"}
    monkeypatch.setattr(library.WeKnoraClient, "from_config", lambda: engine)
    content = "# 审核来源摘要\nNDVI下降是植被变化线索；先核对季节与质量，再结合土地覆盖和SOC。"
    source = tmp_path / "reviewed.md"
    source.write_text(content, encoding="utf-8")
    entry = {
        "seedKey": "eco-reviewed-test-K005",
        "domain": "arid_ecology",
        "title": "两期NDVI的证据范围",
        "category": "生态资料·土地退化监测",
        "subject": "两期NDVI下降",
        "predicate": "可支持",
        "object": "植被变化线索",
        "statement": "两期NDVI变化尚不足以完成SDG15.3.1评价。",
        "explanation": "收集核对与独立审核、发布决定分别保存。",
        "conditions": ["影像质量与季节可比", "UNCCD v2与2025增补"],
        "exceptions": ["按规定方法形成的单项退化仍可触发1OAO"],
        "aliases": ["NDVI", "土地退化", "ECO-K005"],
        "sources": [
            {
                "title": "UNCCD v2",
                "url": "https://www.unccd.int/",
                "locator": "术语表XX",
                "excerpt": "One Out, All Out",
            }
        ],
        "status": "published",
        "ruleKind": "none",
        "ruleConfig": {},
    }
    bundle = {
        "schemaVersion": 1,
        "batch": "ecology-reviewed-test",
        "projectCode": project.code,
        "review": {
            "collectorCheck": "2026-10-13",
            "independentReview": "2026-10-16复核",
            "publicationDecision": "授权发布定性内容",
        },
        "entries": [entry],
        "documents": [
            {
                "title": "审核资料",
                "file": source.name,
                "sourceUrl": "https://www.unccd.int/",
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "reviewStatus": "reviewed_summary",
            }
        ],
    }
    path = tmp_path / "bundle.json"

    def run(payload=None, **options):
        path.write_text(
            json.dumps(payload or bundle, ensure_ascii=False), encoding="utf-8"
        )
        output = StringIO()
        call_command(
            "import_ecology_knowledge",
            bundle=str(path),
            project_code=project.code,
            user_id=user.pk,
            stdout=output,
            **options,
        )
        return json.loads(output.getvalue())

    return SimpleNamespace(
        project=project, user=user, bundle=bundle, run=run, engine=engine, path=path
    )


def test_dry_run_and_repeat_preserve_entries_documents_and_upstream(ecology_import):
    env = ecology_import
    first = env.run(dry_run=True, with_documents=True)
    assert first["created"] == 1 and first["documents"][0]["action"] == "create"
    assert KnowledgeEntry.objects.count() == KnowledgeDocument.objects.count() == 0
    assert OperationLog.objects.count() == 0
    assert not env.engine.upload_file.called
    result = env.run(with_documents=True)
    assert result["created"] == 1 and result["documents"][0]["status"] == "pending"
    assert env.run(with_documents=True)["preserved"] == 1
    assert KnowledgeEntry.objects.count() == KnowledgeRevision.objects.count() == 1
    assert KnowledgeDocument.objects.count() == env.engine.upload_file.call_count == 1
    doc = KnowledgeDocument.objects.get()
    assert doc.domain == "arid_ecology" and doc.project_tag_id == env.project.pk
    assert ":arid_ecology" in doc.library.scope_key
    assert "审核来源摘要" in library._safe_path(doc.extracted_path).read_text(
        encoding="utf-8"
    )


def test_revision_keeps_prior_assertion_and_merges_source(ecology_import):
    env = ecology_import
    env.run()
    old = KnowledgeEntry.objects.get()
    updated = copy.deepcopy(env.bundle)
    updated["entries"][0]["statement"] = (
        "NDVI可作生产力代理，但两期差值不是完整SDG15.3.1评价。"
    )
    updated["entries"][0]["sources"] = [
        {
            "title": "2025增补",
            "url": "https://www.unccd.int/addendum",
            "locator": "§1.2",
        }
    ]
    assert env.run(updated)["updated"] == 1
    current = KnowledgeEntry.objects.get()
    assert current.pk == old.pk and current.revision == 2
    assert current.versions.get(revision=1).snapshot["statement"] == old.statement
    assert current.sources[1]["title"].startswith("历史修订来源：")
    assert env.run(updated)["preserved"] == 1


def test_same_conditions_merge_and_changed_conditions_require_new_key(ecology_import):
    env = ecology_import
    env.run()
    payload = copy.deepcopy(env.bundle)
    payload["entries"][0]["seedKey"] = "another-reviewed-key"
    payload["entries"][0]["conditions"].reverse()
    assert env.run(payload)["preserved"] == 1
    assert KnowledgeEntry.objects.count() == 1
    payload = copy.deepcopy(env.bundle)
    payload["entries"][0]["conditions"] = ["另一地区/资料口径"]
    with pytest.raises(CommandError, match="适用条件已改变"):
        env.run(payload)
    payload["entries"][0]["seedKey"] += "-another-scope"
    assert env.run(payload)["created"] == 1


def test_review_domain_project_and_source_validation_precede_writes(ecology_import):
    env = ecology_import
    variants = []
    for field, value in (("domain", "geology"), ("sources", []), ("conditions", [])):
        bad = copy.deepcopy(env.bundle)
        bad["entries"][0][field] = value
        variants.append(bad)
    bad = copy.deepcopy(env.bundle)
    bad["review"].pop("independentReview")
    variants.append(bad)
    bad = copy.deepcopy(env.bundle)
    bad["projectCode"] = "another-project"
    variants.append(bad)
    for field, value in (
        ("sha256", "invalid"),
        ("file", "../outside.md"),
        ("sourceUrl", "file:///secret"),
        ("reviewStatus", "collector_checked"),
    ):
        bad = copy.deepcopy(env.bundle)
        bad["documents"][0][field] = value
        variants.append(bad)
    for bad in variants:
        with pytest.raises(CommandError):
            env.run(bad, with_documents=True)
    assert KnowledgeEntry.objects.count() == KnowledgeDocument.objects.count() == 0


def test_regular_user_cannot_import_and_other_project_cannot_retrieve(ecology_import):
    env = ecology_import
    env.user.is_superuser = False
    env.user.save()
    ProjectMembership.objects.create(project=env.project, user=env.user)
    with pytest.raises(CommandError, match="维护权限"):
        env.run()
    env.user.is_superuser = True
    env.user.save()
    env.run()
    with project_scope(ProjectScope((env.project.pk,), env.project.pk)):
        found = search_entries(
            env.user, "这片地两期NDVI下降能否认定土地退化", domains=["arid_ecology"]
        )
        assert len(found["items"]) == 1
        assert found["items"][0]["sources"][0]["locator"] == "术语表XX"
    other = Project.objects.create(name="其他项目", code="another-ecology-scope")
    with project_scope(ProjectScope((other.pk,), other.pk)):
        assert search_entries(env.user, "NDVI", domains=["arid_ecology"])["total"] == 0


def test_failed_index_can_retry_without_duplicating_entry_or_document(ecology_import):
    env = ecology_import
    env.run(with_documents=True)
    doc = KnowledgeDocument.objects.get()
    doc.status = "failed"
    doc.save()
    env.engine.reparse_document.return_value = {
        "id": "reviewed-doc",
        "parse_status": "processing",
    }
    retried = env.run(with_documents=True)
    assert retried["preserved"] == 1
    assert retried["documents"][0]["status"] == "processing"
    assert env.engine.reparse_document.call_count == 1
    assert KnowledgeDocument.objects.count() == env.engine.upload_file.call_count == 1
