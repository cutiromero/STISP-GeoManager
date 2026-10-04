import hashlib
import io
import json
from types import SimpleNamespace
from unittest.mock import Mock
from zipfile import ZipFile

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.knowledge import library
from apps.knowledge.models import KnowledgeDocument, KnowledgeLibrary
from apps.knowledge.weknora_client import WeKnoraError
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import Project, ProjectMembership


@pytest.fixture
def env(settings, tmp_path, monkeypatch):
    settings.PROJECT_CONFIG = SimpleNamespace(app_path=lambda *p: tmp_path.joinpath(*p))
    settings.WEKNORA_CONFIG = {
        "enabled": True,
        "api_key": "secret",
        "embedding_model_id": "e",
        "chat_model_id": "c",
    }
    User = get_user_model()
    admin = User.objects.create_superuser("library-admin", password="testing-only")
    reader = User.objects.create_user("library-reader", password="testing-only")
    other = User.objects.create_superuser("library-other", password="testing-only")
    Project.objects.get_or_create(
        pk=1, defaults={"name": "公开", "code": "default", "is_default": True}
    )
    project = Project.objects.create(name="科研资料", code="library-test")
    ProjectMembership.objects.create(project=project, user=reader)
    engine = Mock()
    engine.config.enabled = True
    engine.list_knowledge_bases.return_value = []
    engine.create_knowledge_base.side_effect = lambda name, **kw: {"id": name}
    engine.upload_file.side_effect = lambda kb, **kw: {
        "id": "doc-" + hashlib.sha256(kb.encode() + kw["file"].read()).hexdigest()[:10],
        "parse_status": "pending",
    }
    engine.get_document.return_value = {"parse_status": "completed"}
    engine.reparse_document.side_effect = lambda id: {
        "id": id,
        "parse_status": "pending",
    }
    engine.wiki_stats.return_value = {"pending_tasks": 0, "is_active": False}
    engine.wiki_pages.return_value = {"pages": []}
    engine.hybrid_search.return_value = []
    monkeypatch.setattr(library.WeKnoraClient, "from_config", lambda: engine)
    monkeypatch.setattr(
        library,
        "WeKnoraClient",
        Mock(side_effect=lambda *a: engine, from_config=lambda: engine),
    )
    client = Client()
    client.force_login(admin)
    return SimpleNamespace(
        client=client,
        admin=admin,
        reader=reader,
        other=other,
        project=project,
        engine=engine,
        tmp=tmp_path,
    )


def upload(
    env,
    *,
    project=1,
    visibility="project",
    text="霞石与石英的组合需要判断成因。",
    name="地质.md",
):
    return env.client.post(
        "/api/knowledge/documents/",
        {
            "file": SimpleUploadedFile(name, text.encode()),
            "title": "矿物资料",
            "visibility": visibility,
            "sourceUrl": "https://example.org/mineral",
        },
        HTTP_X_PROJECT_ID=str(project),
    )


def test_upload_real_local_archive_and_separate_permission_domains(env):
    public = upload(env).json()
    shared = upload(env, project=env.project.id).json()
    private = upload(env, project=env.project.id, visibility="owner_only").json()
    assert public["status"] == shared["status"] == private["status"] == "pending"
    assert KnowledgeLibrary.objects.count() == 3
    assert env.engine.upload_file.call_count == 3
    doc = KnowledgeDocument.objects.get(pk=private["id"])
    assert (
        library._safe_path(doc.original_path).read_bytes().decode().startswith("霞石")
    )
    assert (
        "来源：https://example.org/mineral"
        in library._safe_path(doc.extracted_path).read_text()
    )
    env.client.force_login(env.other)
    items = env.client.get(
        "/api/knowledge/documents/", HTTP_X_PROJECT_ID=str(env.project.id)
    ).json()["items"]
    assert {x["id"] for x in items} == {public["id"], shared["id"]}
    assert all("upstream" not in json.dumps(x) for x in items)


def test_duplicate_hash_does_not_submit_again(env):
    one, two = upload(env).json(), upload(env).json()
    assert one["id"] == two["id"]
    assert env.engine.upload_file.call_count == 1
    assert len(list(env.tmp.rglob("*.md"))) == 2  # original + extracted


def test_upload_failure_retains_original_and_retry(env):
    env.engine.upload_file.side_effect = WeKnoraError("服务暂时不可用")
    first = upload(env).json()
    assert first["status"] == "failed"
    doc = KnowledgeDocument.objects.get(pk=first["id"])
    assert library._safe_path(doc.original_path).exists()
    env.engine.upload_file.side_effect = None
    env.engine.upload_file.return_value = {"id": "recovered", "parse_status": "pending"}
    retry = env.client.post(
        f"/api/knowledge/documents/{doc.id}/retry/", HTTP_X_PROJECT_ID="1"
    )
    assert retry.status_code == 200 and retry.json()["status"] == "pending"
    assert (
        env.client.post(
            f"/api/knowledge/documents/{doc.id}/retry/", HTTP_X_PROJECT_ID="1"
        ).status_code
        == 409
    )


def test_reader_cannot_upload_or_retry_owner_only(env):
    private = upload(env, visibility="owner_only").json()
    env.client.force_login(env.reader)
    assert upload(env).status_code == 403
    assert (
        env.client.post(
            f"/api/knowledge/documents/{private['id']}/retry/", HTTP_X_PROJECT_ID="1"
        ).status_code
        == 404
    )


def test_retrieval_drops_upstream_cross_domain_results_and_revoked_membership(env):
    visible = upload(env, project=env.project.id).json()
    secret = upload(env, project=env.project.id, visibility="owner_only").json()
    docs = {d.pk: d for d in KnowledgeDocument.objects.all()}
    env.engine.hybrid_search.return_value = [
        {
            "id": "chunk",
            "knowledge_id": docs[visible["id"]].upstream_document_id,
            "content": "依据",
            "score": 0.8,
            "match_type": 0,
            "chunk_type": "text",
        },
        {
            "id": "leak",
            "knowledge_id": docs[secret["id"]].upstream_document_id,
            "content": "私密",
            "score": 1,
            "match_type": 0,
            "chunk_type": "text",
        },
    ]
    with project_scope(
        ProjectScope((env.project.id,), env.project.id, user_id=env.reader.pk)
    ):
        result = library.search_documents(env.reader, "矿物问题")
        assert [x["documentId"] for x in result["items"]] == [visible["id"]]
        ProjectMembership.objects.filter(project=env.project, user=env.reader).delete()
        with pytest.raises(PermissionDenied):
            library.search_documents(env.reader, "矿物问题")


def test_wiki_rejects_unmapped_sources_and_prunes_links(env):
    doc = KnowledgeDocument.objects.get(pk=upload(env).json()["id"])
    env.engine.wiki_pages.return_value = {
        "pages": [
            {
                "slug": "allowed",
                "title": "可见知识",
                "source_refs": [doc.upstream_document_id + "|原标题"],
                "out_links": None,
            },
            {
                "slug": "hidden",
                "title": "不可见来源",
                "source_refs": [doc.upstream_document_id, "unmapped"],
            },
            {"slug": "unsupported", "title": "没有来源", "source_refs": []},
        ]
    }
    result = library.list_wiki(env.admin)
    assert len(result["items"]) == 1
    assert result["items"][0]["sources"][0]["documentId"] == doc.id
    assert result["items"][0]["links"] == []


def test_document_status_refreshes_from_engine(env):
    upload(env)
    response = env.client.get("/api/knowledge/documents/", HTTP_X_PROJECT_ID="1")
    assert response.status_code == 200
    assert response.json()["items"][0]["status"] == "completed"


def test_generated_summary_is_not_presented_as_original_source(env):
    doc = KnowledgeDocument.objects.get(pk=upload(env).json()["id"])
    env.engine.hybrid_search.return_value = [
        {
            "id": "summary",
            "knowledge_id": doc.upstream_document_id,
            "chunk_type": "summary",
            "content": "模型生成摘要",
            "score": 0.99,
        },
        {
            "id": "original",
            "knowledge_id": doc.upstream_document_id,
            "chunk_type": "text",
            "content": "原始文档段落",
            "score": 0.8,
        },
    ]
    result = library.search_documents(env.admin, "矿物")
    assert len(result["items"]) == 1
    assert result["items"][0]["content"] == "原始文档段落"


def test_upload_requires_explicit_title_and_visibility(env):
    response = env.client.post(
        "/api/knowledge/documents/",
        {
            "file": SimpleUploadedFile("notes.md", b"notes"),
            "title": "资料",
        },
        HTTP_X_PROJECT_ID="1",
    )
    assert response.status_code == 400
    assert KnowledgeDocument.objects.count() == 0


def test_read_original_paginates_and_enforces_owner_boundary(env):
    doc = KnowledgeDocument.objects.get(
        pk=upload(env, visibility="owner_only").json()["id"]
    )
    first = library.read_document(env.admin, doc.id, limit=10)
    second = library.read_document(
        env.admin, doc.id, offset=first["nextOffset"], limit=10
    )
    original = library._safe_path(doc.extracted_path).read_text()
    assert first["content"] + second["content"] == original[:20]
    assert first["documentSha256"] == doc.sha256
    assert "path" not in json.dumps(first)
    assert (
        library.read_document(env.admin, doc.id, offset=len(original))["nextOffset"]
        is None
    )
    with pytest.raises(WeKnoraError) as caught:
        library.read_document(env.other, doc.id)
    assert caught.value.status == 404


def test_front_matter_does_not_outrank_original_body(env):
    doc = KnowledgeDocument.objects.get(pk=upload(env).json()["id"])
    env.engine.hybrid_search.return_value = [
        {
            "id": "toc",
            "knowledge_id": doc.upstream_document_id,
            "chunk_type": "text",
            "content": "Contents\nMineralogy " + "." * 80 + " 3",
            "score": 0.9,
        },
        {
            "id": "body",
            "knowledge_id": doc.upstream_document_id,
            "chunk_type": "text",
            "content": "Primary uranium minerals include uraninite and coffinite.",
            "score": 0.8,
        },
    ]
    result = library.search_documents(env.admin, "铀矿物", limit=1)
    assert result["items"][0]["chunkId"] == "body"


def test_docx_extraction_preserves_paragraph_positions(env):
    path = env.tmp / "test.docx"
    with ZipFile(path, "w") as z:
        z.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>矿物平衡条件</w:t></w:r></w:p></w:body></w:document>',
        )
    assert library._extract(path) == "[原文段落1] 矿物平衡条件"


def test_scanned_pdf_provides_actionable_failure(env):
    from pypdf import PdfWriter

    pdf = PdfWriter()
    pdf.add_blank_page(width=100, height=100)
    stream = io.BytesIO()
    pdf.write(stream)
    response = env.client.post(
        "/api/knowledge/documents/",
        {
            "file": SimpleUploadedFile("扫描.pdf", stream.getvalue()),
            "title": "扫描资料",
            "visibility": "project",
        },
        HTTP_X_PROJECT_ID="1",
    )
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "文字识别" in response.json()["detail"]
    assert env.engine.upload_file.call_count == 0


def test_invalid_pdf_preserves_failed_document(env):
    response = upload(env, text="not a pdf", name="broken.pdf")
    assert response.status_code == 200
    assert response.json()["status"] == "failed"


def test_configuration_failure_and_interrupted_submit_become_retryable(
    env, monkeypatch
):
    from datetime import timedelta
    from django.utils import timezone

    monkeypatch.setattr(
        library.WeKnoraClient,
        "from_config",
        Mock(side_effect=WeKnoraError("知识服务尚未启用")),
    )
    response = upload(env)
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    doc = KnowledgeDocument.objects.get(pk=response.json()["id"])
    KnowledgeDocument.objects.filter(pk=doc.pk).update(
        status="processing", updated_at=timezone.now() - timedelta(minutes=10)
    )
    listing = library.list_documents(env.admin)
    assert listing["items"][0]["status"] == "failed"
    assert "上次提交未完成" in listing["items"][0]["detail"]
