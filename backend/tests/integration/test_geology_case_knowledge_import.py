import copy
import json
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.audit.models import OperationLog
from apps.knowledge.models import KnowledgeEntry, KnowledgeRevision
from apps.projects.models import Project


@pytest.fixture
def import_context(tmp_path):
    project = Project.objects.create(name="真实材料知识", code="case-knowledge")
    user = get_user_model().objects.create_superuser(
        "geology-importer", password="test"
    )
    entry = {
        "seedKey": "geology-case-20261012-test",
        "domain": "geology",
        "title": "八宝山组地层名—时代一致性",
        "category": "专家材料·地层定义",
        "subject": "八宝山组",
        "predicate": "对应地层时代",
        "object": "T3",
        "statement": "辞书条目记八宝山组为T3。",
        "explanation": "辞书定义，先核对地区和图斑绑定。",
        "conditions": ["青海东昆仑南坡", "采用条目06-63-0717"],
        "exceptions": ["不同地区或资料版本分别保留"],
        "aliases": ["八宝山组", "Babaoshan Fm"],
        "sources": [
            {
                "title": "中国岩石地层名称辞典",
                "url": "http://terms.cgl.org.cn/list!termDetails_01.action?dcpId=9a3e4792f3014dfb94b7dc71bba33e55",
                "locator": "06-63-0717；时代字段",
                "excerpt": "T3",
            }
        ],
        "status": "published",
        "ruleKind": "none",
        "ruleConfig": {},
    }
    bundle = {"schemaVersion": 1, "batch": "real-material-test", "entries": [entry]}
    path = tmp_path / "bundle.json"

    def run(payload=None, **options):
        path.write_text(
            json.dumps(payload or bundle, ensure_ascii=False), encoding="utf-8"
        )
        output = StringIO()
        call_command(
            "import_geology_case_knowledge",
            bundle=str(path),
            project_id=project.pk,
            user_id=user.pk,
            stdout=output,
            **options,
        )
        return json.loads(output.getvalue())

    return project, user, bundle, run


def test_import_is_scoped_sourced_and_idempotent(import_context):
    project, _, _, run = import_context
    assert run(dry_run=True)["created"] == 1
    assert KnowledgeEntry.objects.count() == KnowledgeRevision.objects.count() == 0
    assert OperationLog.objects.count() == 0
    assert run()["created"] == 1
    entry = KnowledgeEntry.objects.get()
    assert entry.project_tag_id == project.pk
    assert entry.sources[0]["locator"] == "06-63-0717；时代字段"
    assert entry.versions.get().snapshot["statement"] == entry.statement
    assert run()["preserved"] == 1
    assert KnowledgeEntry.objects.count() == KnowledgeRevision.objects.count() == 1
    assert OperationLog.objects.count() == 1


def test_conflict_uses_new_statement_and_preserves_old_revision(import_context):
    _, _, bundle, run = import_context
    run()
    entry = KnowledgeEntry.objects.get()
    entry.statement = "旧条目误填T2。"
    entry.object = "T2"
    entry.save()
    # A missing old snapshot is created before replacing it.
    entry.versions.all().delete()
    assert run()["updated"] == 1
    entry.refresh_from_db()
    assert entry.object == "T3" and entry.revision == 2
    assert entry.versions.get(revision=1).snapshot["statement"] == "旧条目误填T2。"
    assert (
        entry.versions.get(revision=2).snapshot["statement"]
        == bundle["entries"][0]["statement"]
    )
    assert run()["preserved"] == 1


def test_same_object_different_scope_is_saved_separately(import_context):
    _, _, bundle, run = import_context
    run()
    separate = copy.deepcopy(bundle)
    separate["entries"][0]["seedKey"] += "-different-region"
    separate["entries"][0]["conditions"] = ["另一地区的同名地层", "另一划分版本"]
    assert run(separate)["created"] == 1
    assert KnowledgeEntry.objects.count() == KnowledgeRevision.objects.count() == 2


def test_semantic_duplicate_merges_sources_and_updates_existing_id(import_context):
    _, _, bundle, run = import_context
    run()
    old_id = KnowledgeEntry.objects.get().id
    duplicate = copy.deepcopy(bundle)
    duplicate["entries"][0]["seedKey"] = "another-reviewed-source"
    duplicate["entries"][0]["conditions"].reverse()
    duplicate["entries"][0]["sources"] = [
        {"title": "同范围补充依据", "locator": "本区调查记录第2条", "excerpt": "T3"}
    ]
    result = run(duplicate)
    assert result["updated"] == 1
    entry = KnowledgeEntry.objects.get()
    assert entry.id == old_id and len(entry.sources) == 2
    assert run(duplicate)["preserved"] == 1


def test_validation_and_scope_changes_are_atomic(import_context):
    _, _, bundle, run = import_context
    run()
    changed_scope = copy.deepcopy(bundle)
    changed_scope["entries"][0]["conditions"] = ["另一区域"]
    with pytest.raises(CommandError, match="适用条件已改变"):
        run(changed_scope)
    invalid = copy.deepcopy(bundle)
    invalid["entries"].append(
        {**invalid["entries"][0], "seedKey": "other", "sources": []}
    )
    with pytest.raises(CommandError, match="发布知识需要"):
        run(invalid)
    assert KnowledgeEntry.objects.count() == KnowledgeRevision.objects.count() == 1


def test_readonly_user_cannot_import(import_context):
    _, user, _, run = import_context
    user.is_superuser = False
    user.is_staff = False
    user.save()
    with pytest.raises(CommandError):
        run()
    assert KnowledgeEntry.objects.count() == 0


def test_replaced_assertion_labels_older_sources_as_history(import_context):
    _, _, _, run = import_context
    run()
    entry = KnowledgeEntry.objects.get()
    entry.statement = "旧条目误填T2。"
    entry.sources = [{"title": "旧材料", "locator": "旧材料第3页", "excerpt": "T2"}]
    entry.save()
    assert run()["updated"] == 1
    entry.refresh_from_db()
    assert entry.sources[0]["title"] == "中国岩石地层名称辞典"
    assert entry.sources[1]["title"].startswith("历史修订来源（旧断言）：")
    assert (
        entry.versions.get(revision=1).snapshot["sources"][0]["title"]
        == "中国岩石地层名称辞典"
    )
