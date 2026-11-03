"""Authorized document ingestion and official WeKnora retrieval/Wiki bridge."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
import io
import math
from pathlib import Path
import re
from uuid import uuid4
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError
from django.db.models import Q
from django.utils import timezone
from apps.projects.access import public_project_allowed

from .models import KnowledgeDocument, KnowledgeLibrary
from .services import can_edit, require_project
from .domains import validate_domain, validate_domains
from .weknora_client import WeKnoraClient, WeKnoraError, configured_weknora

MAX_BYTES = 20 * 1024 * 1024
MAX_TEXT = 1_000_000
STATUSES = {"pending", "processing", "finalizing", "completed", "failed", "cancelled"}


def visible_documents(user, domains=None):
    if not get_user_model().objects.filter(pk=user.pk, is_active=True).exists():
        raise PermissionDenied("账号已停用")
    pid = require_project(user)
    # Explicit public inclusion: default manager is scoped to the selected project.
    project_filter = Q(project_tag_id=pid)
    if public_project_allowed(user):
        project_filter |= Q(project_tag_id=1, visibility="project")
    qs = (
        KnowledgeDocument._base_manager.select_related("library")
        .filter(project_filter)
        .filter(Q(visibility="project") | Q(visibility="owner_only", owner_id=user.pk))
    )
    return (
        qs.filter(domain__in=validate_domains(domains)) if domains is not None else qs
    )


def _can_manage(user, doc):
    return (
        can_edit(user)
        and doc.project_tag_id == require_project(user)
        and (doc.visibility == "project" or doc.owner_id == user.pk)
    )


def serialize_document(user, doc):
    return {
        "id": doc.id,
        "domain": doc.domain,
        "title": doc.title,
        "filename": doc.filename,
        "sourceUrl": doc.source_url,
        "projectTagId": doc.project_tag_id,
        "visibility": doc.visibility,
        "status": doc.status,
        "detail": doc.detail,
        "createdAt": doc.created_at.isoformat(),
        "sha256": doc.sha256,
        "canManage": _can_manage(user, doc),
    }


def _library(user, visibility, domain="geology"):
    pid = require_project(user)
    owner_id = user.pk if visibility == "owner_only" else None
    scope_key = f"project:{pid}:{visibility}:{owner_id or 0}"
    # Retain the legacy geological library; new areas get separate upstream Wiki spaces.
    if domain != "geology":
        scope_key += f":{domain}"
    library, _ = KnowledgeLibrary.objects.get_or_create(
        scope_key=scope_key,
        defaults={
            "project_tag_id": pid,
            "visibility": visibility,
            "owner_id": owner_id,
        },
    )
    return library


def _provision(library, client):
    if library.upstream_kb_id:
        return library.upstream_kb_id
    # The CAS prevents multiple application processes creating the same domain.
    claimed = (
        KnowledgeLibrary.objects.filter(pk=library.pk)
        .filter(
            Q(provisioning=False)
            | Q(updated_at__lt=timezone.now() - timedelta(minutes=3))
        )
        .update(provisioning=True, updated_at=timezone.now())
    )
    if not claimed:
        raise WeKnoraError("该知识空间正在初始化，请稍后重试", status=409)
    try:
        name = "STISP " + library.scope_key
        existing = client.list_knowledge_bases()
        if isinstance(existing, dict):
            existing = existing.get("knowledge_bases", existing.get("items", []))
        kb = next((x for x in existing if x.get("name") == name), None)
        if kb is None:
            kb = client.create_knowledge_base(
                name, description="由时空智能平台维护的独立知识权限空间"
            )
        kb_id = kb.get("id")
        if not isinstance(kb_id, str) or not kb_id:
            raise WeKnoraError("知识空间初始化未返回有效标识")
        KnowledgeLibrary.objects.filter(pk=library.pk).update(upstream_kb_id=kb_id)
        library.upstream_kb_id = kb_id
        return kb_id
    finally:
        KnowledgeLibrary.objects.filter(pk=library.pk).update(provisioning=False)


def _safe_path(relative):
    base = settings.PROJECT_CONFIG.app_path("uploads", "knowledge").resolve()
    path = (base / relative).resolve()
    if not path.is_relative_to(base):
        raise ValidationError("知识资料路径无效")
    return path


def _extract(path):
    from pypdf.errors import PyPdfError

    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(path)
            if reader.is_encrypted:
                raise ValidationError("请先解除PDF密码后上传")
            if len(reader.pages) > 500:
                raise ValidationError("PDF最多500页，请按章节拆分")
            parts, count = [], 0
            has_text = False
            for index, page in enumerate(reader.pages, 1):
                content = page.extract_text() or ""
                has_text |= bool(re.search(r"[\w\u4e00-\u9fff]", content))
                count += len(content)
                if count > MAX_TEXT:
                    raise ValidationError("资料文字超过100万字，请按章节拆分")
                parts.append(f"## 原文第{index}页\n\n{content}")
            if not has_text:
                raise ValidationError("PDF没有可提取文字，请先进行文字识别后上传")
            text = "\n\n".join(parts)
        elif suffix == ".docx":
            with ZipFile(path) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > 16 * 1024 * 1024:
                    raise ValidationError("Word正文过大，请拆分文件")
                data = archive.read(info)
            if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
                raise ValidationError("Word正文包含不支持的XML定义")
            root = ElementTree.fromstring(data)
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            parts = []
            for index, paragraph in enumerate(root.findall(".//w:p", ns), 1):
                words = "".join(
                    t.text or "" for t in paragraph.findall(".//w:t", ns)
                ).strip()
                if words:
                    parts.append(f"[原文段落{index}] {words}")
            text = "\n\n".join(parts)
        else:
            data = path.read_bytes()
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = data.decode("gb18030")
    except ValidationError:
        raise
    except (
        OSError,
        ValueError,
        KeyError,
        BadZipFile,
        ElementTree.ParseError,
        ImportError,
        PyPdfError,
    ) as exc:
        raise ValidationError("资料解析失败，请检查文件内容和格式后重试") from exc
    if not text.strip():
        raise ValidationError("资料没有可索引的文字")
    if len(text) > MAX_TEXT:
        raise ValidationError("资料文字超过100万字，请按章节拆分")
    return text


def _submit(doc, user):
    if not _can_manage(user, doc):
        raise PermissionDenied("只能处理当前项目中有权维护的资料")
    try:
        client = WeKnoraClient.from_config()
        kb_id = _provision(doc.library, client)
        if doc.upstream_document_id:
            upstream = client.reparse_document(doc.upstream_document_id)
        else:
            text = _extract(_safe_path(doc.original_path))
            extracted = _safe_path(doc.original_path).with_suffix(".extracted.md")
            content = (
                f"# {doc.title}\n\n来源：{doc.source_url or doc.filename}\n\n{text}"
            )
            extracted.write_text(content, encoding="utf-8")
            doc.extracted_path = str(
                Path(doc.original_path).with_suffix(".extracted.md")
            )
            # Official file ingestion deduplicates identical bytes in this KB;
            # an interrupted response can be retried without duplicating Wiki.
            upstream = client.upload_file(
                kb_id,
                filename=f"{doc.sha256}.md",
                file=io.BytesIO(content.encode("utf-8")),
                display_name=doc.title + ".md",
            )
        upstream_id = upstream.get("id")
        if not isinstance(upstream_id, str) or not upstream_id:
            raise WeKnoraError("知识服务未返回资料标识，请稍后重试")
        doc.upstream_document_id = upstream_id
        doc.status = upstream.get("parse_status", "pending")
        if doc.status not in STATUSES:
            doc.status = "pending"
        doc.detail = (
            "文档处理失败，可重试"
            if doc.status == "failed"
            else "已提交文档索引与Wiki整理"
        )
    except (WeKnoraError, ValidationError) as exc:
        doc.status = "failed"
        doc.detail = (
            "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
        )
    doc.save(
        update_fields=(
            "upstream_document_id",
            "extracted_path",
            "status",
            "detail",
            "updated_at",
        )
    )
    return doc


def upload_document(
    user, file, *, title, source_url="", visibility="project", domain="geology"
):
    pid = require_project(user)
    domain = validate_domain(domain)
    if not can_edit(user):
        raise PermissionDenied("需要知识维护权限")
    title = title.strip()
    if not title or len(title) > 180:
        raise ValidationError("标题须为1至180字")
    if visibility not in {"project", "owner_only"}:
        raise ValidationError("资料可见范围无效")
    source_url = source_url.strip()
    if source_url:
        if len(source_url) > 2000:
            raise ValidationError("来源地址过长")
        URLValidator(schemes=("http", "https"))(source_url)
    filename = Path(str(file.name).replace("\\", "/")).name
    suffix = Path(filename).suffix.lower()
    if (
        suffix not in {".pdf", ".docx", ".txt", ".md", ".csv", ".json"}
        or len(filename) > 255
    ):
        raise ValidationError("请上传PDF、DOCX、TXT、MD、CSV或JSON资料")
    if file.size > MAX_BYTES:
        raise ValidationError("知识资料不能超过20MiB")
    library = _library(user, visibility, domain)
    relative = f"{pid}/{uuid4().hex}{suffix}"
    path = _safe_path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    sha, size = hashlib.sha256(), 0
    try:
        with path.open("xb") as target:
            for chunk in file.chunks():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValidationError("知识资料不能超过20MiB")
                sha.update(chunk)
                target.write(chunk)
        digest = sha.hexdigest()
        existing = KnowledgeDocument.objects.filter(
            library=library, sha256=digest
        ).first()
        if existing:
            path.unlink()
            return existing
        try:
            doc = KnowledgeDocument.objects.create(
                project_tag_id=pid,
                library=library,
                owner=user,
                title=title,
                domain=domain,
                filename=filename,
                source_url=source_url,
                visibility=visibility,
                sha256=digest,
                original_path=relative,
                status="processing",
            )
        except IntegrityError:
            path.unlink()
            return KnowledgeDocument.objects.get(library=library, sha256=digest)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return _submit(doc, user)


def retry_document(user, doc_id):
    doc = visible_documents(user).filter(pk=doc_id).first()
    if doc is None:
        raise WeKnoraError("资料不存在或无权访问", status=404)
    if not _can_manage(user, doc):
        raise PermissionDenied("只能重新处理当前项目中有权维护的资料")
    changed = KnowledgeDocument.objects.filter(
        pk=doc.pk, status__in=("failed", "cancelled")
    ).update(status="processing", detail="正在重新处理", updated_at=timezone.now())
    if not changed:
        raise WeKnoraError("资料仍在处理或已经完成，请刷新状态", status=409)
    doc.status = "processing"
    return _submit(doc, user)


def classify_document(user, doc_id, domain):
    domain = validate_domain(domain)
    doc = visible_documents(user).filter(pk=doc_id).first()
    if doc is None:
        raise WeKnoraError("资料不存在或无权访问", status=404)
    if not _can_manage(user, doc):
        raise PermissionDenied("只能维护当前项目中有权访问的资料")
    doc.domain = domain
    doc.save(update_fields=["domain", "updated_at"])
    return doc


def list_documents(user, domains=None):
    query = visible_documents(user, domains)
    # A terminated upload process has no upstream task to poll. Preserve the
    # original and make it retryable once its bounded request window expired.
    query.filter(
        status="processing",
        upstream_document_id="",
        updated_at__lt=timezone.now() - timedelta(minutes=5),
    ).update(status="failed", detail="上次提交未完成，原始资料已保留，可重新处理")
    config = configured_weknora()
    detail = "文档知识服务已启用" if config.enabled else "文档知识服务尚未启用"
    if config.enabled:
        client = WeKnoraClient(config)
        candidates = list(
            query.filter(status__in=("pending", "processing", "finalizing"))
            .filter(
                Q(last_checked_at__isnull=True)
                | Q(last_checked_at__lt=timezone.now() - timedelta(seconds=5))
            )
            .exclude(upstream_document_id="")[:10]
        )

        # Network calls parallelize; every database read/write stays in this thread.
        def fetch(doc):
            return doc, client.get_document(doc.upstream_document_id)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(fetch, d) for d in candidates]
            for future in futures:
                try:
                    doc, upstream = future.result()
                    status = upstream.get("parse_status")
                    if status not in STATUSES:
                        continue
                    message = (
                        "索引完成，可检索；Wiki整理进度见专题页"
                        if status == "completed"
                        else "正在处理资料"
                    )
                    if status == "failed":
                        message = "知识引擎处理失败，可重试；原始资料已保留"
                    KnowledgeDocument._base_manager.filter(pk=doc.pk).update(
                        status=status,
                        detail=message,
                        last_checked_at=timezone.now(),
                        updated_at=timezone.now(),
                    )
                except WeKnoraError as exc:
                    detail = str(exc)
    return {
        "items": [serialize_document(user, d) for d in query[:200]],
        "enabled": config.enabled,
        "canUpload": can_edit(user),
        "detail": detail,
    }


def read_document(user, document_id, offset=0, limit=8000, domains=None):
    """Read an authorized local extraction, with stable character pagination."""
    if type(document_id) is not int or document_id < 1:
        raise ValidationError("资料编号无效")
    if type(offset) is not int or offset < 0:
        raise ValidationError("原文起始位置须为非负整数")
    if type(limit) is not int or not 1 <= limit <= 8000:
        raise ValidationError("单次读取须为1至8000字")
    doc = visible_documents(user, domains).filter(pk=document_id).first()
    if doc is None:
        raise WeKnoraError("资料不存在或无权访问", status=404)
    if not doc.extracted_path:
        raise WeKnoraError("资料尚未完成文字提取，请先重新处理", status=409)
    try:
        text = _safe_path(doc.extracted_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise WeKnoraError("原文暂时无法读取，请联系资料维护者", status=409) from exc
    if (
        not visible_documents(user, domains)
        .filter(pk=document_id, sha256=doc.sha256)
        .exists()
    ):
        raise WeKnoraError("资料不存在或无权访问", status=404)
    start = min(offset, len(text))
    end = min(start + limit, len(text))
    return {
        "documentId": doc.id,
        "domain": doc.domain,
        "title": doc.title,
        "sourceUrl": doc.source_url,
        "documentSha256": doc.sha256,
        "content": text[start:end],
        "offset": start,
        "nextOffset": end if end < len(text) else None,
        "truncated": end < len(text),
        "totalCharacters": len(text),
        "sourceKind": "document_excerpt",
    }


def _source_quality(content):
    """Downrank navigational front matter; never rewrite the source quotation."""
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    leaders = sum(len(match.group()) for match in re.finditer(r"\.{6,}|…{3,}", content))
    if leaders > len(content) * 0.2:
        return 0.1
    lower = content.lower()
    boilerplate = (
        "for product and ordering information",
        "telephone: 1-888-ask-usgs",
        "any use of trade, product, or firm names",
        "copyright owners to reproduce",
    )
    if sum(term in lower for term in boilerplate) >= 2:
        return 0.2
    if (
        lines
        and len(content) < 350
        and any(term in lower for term in ("mail stop", "telephone:", "web site at:"))
    ):
        return 0.2
    return 1.0


def search_documents(user, query, limit=6, domains=None):
    if not isinstance(query, str) or not query.strip() or len(query) > 1000:
        raise ValidationError("检索问题须为1至1000字")
    if type(limit) is not int or not 1 <= limit <= 12:
        raise ValidationError("检索数量须为1至12")
    docs = list(visible_documents(user, domains).exclude(upstream_document_id=""))
    mapping = {d.upstream_document_id: d for d in docs}
    groups = {}
    for doc in docs:
        if doc.library.upstream_kb_id and doc.status not in {"failed", "cancelled"}:
            groups.setdefault(doc.library.upstream_kb_id, []).append(
                doc.upstream_document_id
            )
    client = WeKnoraClient.from_config()
    if not client.config.enabled:
        return {"items": [], "available": False, "detail": "文档知识服务尚未启用"}
    items = []
    try:
        for kb_id, ids in groups.items():
            for hit in client.hybrid_search(
                kb_id, query.strip(), limit=min(20, limit * 3), document_ids=ids
            ):
                # WeKnora also indexes generated summaries, entity descriptions
                # and Wiki pages. Only source text is a document quotation.
                if hit.get("chunk_type") not in {"text", "parent_text"}:
                    continue
                doc = mapping.get(hit.get("knowledge_id"))
                if not doc or doc.upstream_document_id not in ids:
                    continue
                content = str(hit.get("content", ""))[:12000]
                score = float(hit.get("score", 0)) * _source_quality(content)
                if not math.isfinite(score):
                    continue
                items.append(
                    {
                        "documentId": doc.id,
                        "domain": doc.domain,
                        "title": doc.title,
                        "sourceUrl": doc.source_url,
                        "content": content,
                        "score": score,
                        "matchType": "keyword"
                        if hit.get("match_type") == 1
                        else "vector",
                        "chunkId": str(hit.get("id", "")),
                    }
                )
    except WeKnoraError as exc:
        return {"items": [], "available": False, "detail": str(exc)}
    # Recheck local access after upstream I/O, including project/account revocation.
    allowed = set(visible_documents(user, domains).values_list("id", flat=True))
    items = [x for x in items if x["documentId"] in allowed]
    items.sort(key=lambda x: x["score"], reverse=True)
    return {
        "items": items[:limit],
        "available": True,
        "detail": "原文语义与关键词混合检索",
    }


def list_wiki(user, domains=None):
    docs = list(visible_documents(user, domains).exclude(upstream_document_id=""))
    mapping = {d.upstream_document_id: d for d in docs}
    libraries = {d.library_id: d.library for d in docs if d.library.upstream_kb_id}
    result = {
        "items": [],
        "pendingTasks": 0,
        "active": False,
        "available": True,
        "detail": "由资料自动整理，来源可追溯",
    }
    client = WeKnoraClient.from_config()
    if not client.config.enabled:
        return {**result, "available": False, "detail": "文档知识服务尚未启用"}
    try:
        for library in libraries.values():
            stats = client.wiki_stats(library.upstream_kb_id)
            result["pendingTasks"] += max(0, int(stats.get("pending_tasks", 0)))
            result["active"] |= bool(stats.get("is_active"))
            pages = client.wiki_pages(library.upstream_kb_id, page_size=100).get(
                "pages", []
            )
            for page in pages:
                refs = page.get("source_refs", [])
                # Official Wiki supports both knowledgeID and knowledgeID|title.
                if isinstance(refs, list) and all(isinstance(ref, str) for ref in refs):
                    refs = list(dict.fromkeys(ref.split("|", 1)[0] for ref in refs))
                if (
                    not isinstance(refs, list)
                    or not refs
                    or any(
                        not isinstance(ref, str)
                        or ref not in mapping
                        or mapping[ref].library_id != library.id
                        for ref in refs
                    )
                ):
                    continue
                slug = page.get("slug", "")
                sources = [
                    {
                        "documentId": mapping[ref].id,
                        "domain": mapping[ref].domain,
                        "title": mapping[ref].title,
                        "sourceUrl": mapping[ref].source_url,
                    }
                    for ref in refs
                ]
                result["items"].append(
                    {
                        "id": f"{library.id}:{slug}",
                        "domain": mapping[refs[0]].domain,
                        "title": page.get("title", ""),
                        "summary": page.get("summary") or "",
                        "content": (page.get("content") or "")[:50000],
                        "status": page.get("status", "draft"),
                        "version": int(page.get("version", 1)),
                        "sources": sources,
                        "links": [
                            f"{library.id}:{s}" for s in (page.get("out_links") or [])
                        ],
                        "projectTagId": library.project_tag_id,
                    }
                )
    except WeKnoraError as exc:
        return {**result, "items": [], "available": False, "detail": str(exc)}
    allowed = set(visible_documents(user, domains).values_list("id", flat=True))
    result["items"] = [
        p
        for p in result["items"]
        if all(s["documentId"] in allowed for s in p["sources"])
    ][:100]
    ids = {p["id"] for p in result["items"]}
    for page in result["items"]:
        page["links"] = [link for link in page["links"] if link in ids]
    return result
