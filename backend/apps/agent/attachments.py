"""Safe storage and bounded extraction for files attached to an agent run."""

from __future__ import annotations

import hashlib
import io
import re
import zlib
from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree

from django.core.exceptions import ValidationError

from apps.core.storage import app_path

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_EXTRACTED_CHARACTERS = 120_000
MAX_ATTACHMENTS_PER_CONVERSATION = 8

DOCUMENT_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".csv"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _safe_name(name: str) -> tuple[str, str, str]:
    original = Path(str(name or "")).name.strip()
    if not original or len(original) > 255:
        raise ValidationError("附件文件名无效")
    suffix = Path(original).suffix.lower()
    if suffix in DOCUMENT_SUFFIXES:
        kind = "document"
    elif suffix in IMAGE_SUFFIXES:
        kind = "image"
    else:
        raise ValidationError("仅支持 PDF、DOCX、TXT、MD、CSV、PNG、JPG、JPEG 和 WebP")
    return original, suffix, kind


def _pdf_text(payload: bytes) -> str:
    """Extract basic PDF text without executing embedded content.

    The deployment does not require a PDF renderer. This parser handles the
    common text operators emitted by office/scientific exporters and returns
    an explicit empty result for image-only/scanned PDFs; those can still be
    uploaded and later sent to a vision-capable model as a document is not
    silently treated as text.
    """

    chunks: list[bytes] = []
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", payload, re.DOTALL):
        stream = match.group(1)
        start = max(0, payload.rfind(b"<<", 0, match.start()))
        header = payload[start : match.start()]
        if b"/FlateDecode" in header:
            try:
                stream = zlib.decompress(stream)
            except zlib.error:
                continue
        chunks.append(stream)
    text: list[str] = []
    for stream in chunks:
        for block in re.findall(rb"BT(.*?)ET", stream, re.DOTALL):
            for raw in re.findall(rb"\((?:\\.|[^\\)])*\)", block):
                value = raw[1:-1]
                value = re.sub(rb"\\([\\()\\\\])", rb"\1", value)
                value = re.sub(rb"\\[nrt]", b" ", value)
                text.append(value.decode("utf-8", errors="replace"))
            for raw in re.findall(rb"<([0-9A-Fa-f]{4,})>\s*T[Jj]", block):
                try:
                    text.append(bytes.fromhex(raw.decode()).decode("utf-16-be", errors="replace"))
                except (ValueError, UnicodeError):
                    continue
    return "\n".join(text)


def _docx_text(payload: bytes) -> str:
    try:
        with ZipFile(io.BytesIO(payload)) as archive:
            xml = archive.read("word/document.xml")
    except (BadZipFile, KeyError) as exc:
        raise ValidationError("DOCX 文件损坏或缺少正文") from exc
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise ValidationError("DOCX 正文无法解析") from exc
    values: list[str] = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] == "t" and node.text:
            values.append(node.text)
        elif node.tag.rsplit("}", 1)[-1] == "br":
            values.append("\n")
    return "".join(values)


def extract_text(payload: bytes, suffix: str) -> tuple[str, str]:
    if suffix in {".txt", ".md", ".csv"}:
        text = payload.decode("utf-8-sig", errors="replace")
    elif suffix == ".docx":
        text = _docx_text(payload)
    elif suffix == ".pdf":
        text = _pdf_text(payload)
    else:
        return "", "not_applicable"
    text = text.replace("\x00", "").strip()
    if len(text) > MAX_EXTRACTED_CHARACTERS:
        return text[:MAX_EXTRACTED_CHARACTERS], "truncated"
    return text, "ready" if text else "empty"


def validate_image(payload: bytes, suffix: str) -> str:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.verify()
            width, height = image.size
            if not width or not height or width * height > 100_000_000:
                raise ValidationError("图片尺寸超过安全限制")
            actual = (image.format or "").lower()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationError("图片文件无效") from exc
    expected = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".webp": "webp"}[suffix]
    if actual != expected:
        raise ValidationError("图片扩展名与实际格式不一致")
    return f"image/{'jpeg' if expected == 'jpeg' else expected}"


def store_attachment(*, conversation, owner, upload, max_bytes=MAX_ATTACHMENT_BYTES, max_count=MAX_ATTACHMENTS_PER_CONVERSATION):
    if owner.pk != conversation.owner_id:
        raise ValidationError("只能上传到自己的会话")
    original, suffix, kind = _safe_name(upload.name)
    size = int(getattr(upload, "size", 0) or 0)
    max_bytes = min(MAX_ATTACHMENT_BYTES, max(1024, int(max_bytes)))
    if size <= 0 or size > max_bytes:
        raise ValidationError("附件大小超过管理员设置的上限")
    payload = upload.read(max_bytes + 1)
    if len(payload) != size or len(payload) > max_bytes:
        raise ValidationError("附件大小超过管理员设置的上限")
    digest = hashlib.sha256(payload).hexdigest()
    existing = conversation.attachments.filter(checksum=digest).first()
    if existing:
        return existing
    if conversation.attachments.count() >= max(1, min(MAX_ATTACHMENTS_PER_CONVERSATION, int(max_count))):
        raise ValidationError("每个会话的附件数量已达管理员设置上限")
    if kind == "image":
        mime_type = validate_image(payload, suffix)
        extracted, extraction_status = "", "not_applicable"
    else:
        mime_type = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".csv": "text/csv",
        }[suffix]
        if suffix == ".pdf" and not payload.startswith(b"%PDF-"):
            raise ValidationError("PDF 文件签名无效")
        extracted, extraction_status = extract_text(payload, suffix)
    relative = f"projects/{conversation.project_tag_id}/agent-attachments/{uuid4().hex}{suffix}"
    target = app_path(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    try:
        from .models import AgentAttachment

        return AgentAttachment.objects.create(
            project_tag_id=conversation.project_tag_id,
            owner=owner,
            conversation=conversation,
            name=original,
            path=relative,
            mime_type=mime_type,
            kind=kind,
            size_bytes=size,
            checksum=digest,
            extracted_text=extracted,
            extraction_status=extraction_status,
        )
    except Exception:
        target.unlink(missing_ok=True)
        raise


def delete_attachment(attachment):
    target = app_path(attachment.path)
    attachment.delete()
    target.unlink(missing_ok=True)


def serialize_attachment(attachment):
    return {
        "id": attachment.pk,
        "fileName": attachment.name,
        "kind": attachment.kind,
        "mediaType": attachment.mime_type,
        "sizeBytes": attachment.size_bytes,
        # Preview is intentionally omitted: files remain behind the same
        # authenticated conversation API and are sent server-side to the
        # model.  An empty value keeps the contract explicit.
        "previewUrl": "",
        "extractedText": attachment.extracted_text[:2000],
        "createdAt": attachment.created_at.isoformat(),
    }
