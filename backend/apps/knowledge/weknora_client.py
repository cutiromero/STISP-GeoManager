"""Private transport to the official WeKnora API; callers enforce local scope.

Every KB/document identifier must come from an authorized local mapping. Never
pass browser-supplied upstream identifiers directly into this client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import ipaddress
import json
from pathlib import Path
import socket
import tomllib
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

from django.conf import settings


class WeKnoraError(RuntimeError):
    """Safe public-facing error without upstream bodies, addresses or secrets."""

    def __init__(self, message: str, *, status: int = 503):
        super().__init__(message)
        self.status = status


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class WeKnoraConfig:
    enabled: bool = False
    base_url: str = "http://127.0.0.1:18080"
    api_key: str = field(default="", repr=False)
    tenant_id: int = 0
    timeout_seconds: float = 20
    embedding_model_id: str = ""
    chat_model_id: str = ""
    max_response_bytes: int = 8 * 1024 * 1024


def configured_weknora() -> WeKnoraConfig:
    """Read deployment-only configuration. No credentials reach frontend DTOs."""
    raw = getattr(settings, "WEKNORA_CONFIG", None)
    if raw is None:
        with settings.PROJECT_CONFIG.config_path.open("rb") as handle:
            raw = (
                tomllib.load(handle)
                .get("application", {})
                .get("knowledge", {})
                .get("weknora", {})
            )
    if not isinstance(raw, dict):
        raise WeKnoraError("知识服务配置无效")
    values = {
        key: value
        for key, value in raw.items()
        if key in WeKnoraConfig.__dataclass_fields__
    }
    # Secret files are optional; keep them outside code and generated contracts.
    if raw.get("api_key_file"):
        try:
            values["api_key"] = (
                Path(raw["api_key_file"]).read_text(encoding="utf-8").strip()
            )
        except (OSError, TypeError) as exc:
            raise WeKnoraError("知识服务凭据不可读取") from exc
    try:
        return WeKnoraConfig(**values)
    except (TypeError, ValueError) as exc:
        raise WeKnoraError("知识服务配置无效") from exc


def _part(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 1000:
        raise WeKnoraError("知识服务标识无效", status=400)
    return quote(value, safe="")


class WeKnoraClient:
    def __init__(self, config: WeKnoraConfig, *, bearer_token: str = ""):
        self.config = config
        self._bearer_token = bearer_token
        parsed = urlsplit(config.base_url)
        try:
            loopback = ipaddress.ip_address(parsed.hostname or "").is_loopback
            port = parsed.port
            valid_limits = (
                isinstance(config.enabled, bool)
                and 1 <= float(config.timeout_seconds) <= 120
                and 1024 <= int(config.max_response_bytes) <= 32 * 1024 * 1024
            )
        except (ValueError, TypeError):
            loopback, port, valid_limits = False, None, False
        if (
            not loopback
            or parsed.scheme not in {"http", "https"}
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
            or port is None
            or not valid_limits
        ):
            raise WeKnoraError("知识服务需配置为本机专用地址")
        self._base = config.base_url.rstrip("/")
        # Disable environment proxies and redirects to prevent credential escape.
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    @classmethod
    def from_config(cls) -> WeKnoraClient:
        return cls(configured_weknora())

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Any = None,
        query: dict | None = None,
        body: bytes | None = None,
        content_type: str = "application/json",
        authenticated: bool = True,
        duplicate_kb_id: str = "",
    ) -> Any:
        if not self.config.enabled:
            raise WeKnoraError("文档知识服务尚未启用")
        headers = {"Accept": "application/json", "Accept-Language": "zh-CN"}
        if authenticated:
            if self._bearer_token:
                headers["Authorization"] = f"Bearer {self._bearer_token}"
            elif self.config.api_key:
                headers["X-API-Key"] = self.config.api_key
            else:
                raise WeKnoraError("知识服务凭据尚未配置")
            if self.config.tenant_id:
                headers["X-Tenant-ID"] = str(self.config.tenant_id)
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(
                "utf-8"
            )
        if body is not None:
            headers["Content-Type"] = content_type
        url = self._base + path
        if query:
            url += "?" + urlencode(query)
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with self._opener.open(
                request, timeout=self.config.timeout_seconds
            ) as response:
                data = response.read(self.config.max_response_bytes + 1)
            if len(data) > self.config.max_response_bytes:
                raise WeKnoraError("知识服务响应过大，请缩小查询范围")
            result = json.loads(data) if data else {}
        except HTTPError as exc:
            status = exc.code
            if status == 409 and duplicate_kb_id:
                try:
                    duplicate = json.loads(exc.read(self.config.max_response_bytes + 1))
                    existing = duplicate.get("data", {})
                    if (
                        duplicate.get("code") == "duplicate_file"
                        and isinstance(existing, dict)
                        and existing.get("id")
                        and existing.get("knowledge_base_id") == duplicate_kb_id
                    ):
                        return existing
                except (ValueError, AttributeError, TypeError):
                    pass
                finally:
                    exc.close()
            exc.close()
            if status == 404:
                raise WeKnoraError("知识服务中的记录不存在", status=404) from exc
            if status in {401, 403}:
                raise WeKnoraError("知识服务访问凭据无效或权限不足") from exc
            raise WeKnoraError("知识服务处理失败，请稍后重试") from exc
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise WeKnoraError("知识服务暂时无法连接，请稍后重试") from exc
        except (ValueError, UnicodeError) as exc:
            raise WeKnoraError("知识服务返回了无法识别的响应") from exc
        if isinstance(result, dict) and result.get("success") is False:
            raise WeKnoraError("知识服务处理失败，请稍后重试")
        if isinstance(result, dict) and "data" in result and "success" in result:
            return result["data"]
        return result

    def health(self) -> dict:
        return self._request("GET", "/health", authenticated=False)

    def register(self, *, email: str, password: str, username: str) -> dict:
        return self._request(
            "POST",
            "/api/v1/auth/register",
            authenticated=False,
            payload={"email": email, "password": password, "username": username},
        )

    def login(self, *, email: str, password: str) -> dict:
        return self._request(
            "POST",
            "/api/v1/auth/login",
            authenticated=False,
            payload={"email": email, "password": password},
        )

    def create_tenant(self, name: str, description: str = "") -> dict:
        """Requires privileged bearer/platform credentials; not a Lite UI feature."""
        return self._request(
            "POST",
            "/api/v1/tenants",
            payload={"name": name, "description": description},
        )

    def list_models(self) -> list:
        return self._request("GET", "/api/v1/models")

    def create_model(self, *, name: str, model_type: str, parameters: dict) -> dict:
        if model_type not in {"Embedding", "KnowledgeQA"}:
            raise WeKnoraError("知识模型类型无效", status=400)
        return self._request(
            "POST",
            "/api/v1/models",
            payload={
                "name": name,
                "display_name": name,
                "type": model_type,
                "source": "remote",
                "parameters": parameters,
            },
        )

    def list_knowledge_bases(self) -> list:
        return self._request("GET", "/api/v1/knowledge-bases")

    def create_knowledge_base(
        self, name: str, *, description: str = "", wiki_enabled: bool = True
    ) -> dict:
        if not self.config.embedding_model_id or (
            wiki_enabled and not self.config.chat_model_id
        ):
            raise WeKnoraError("知识服务的向量或整理模型尚未配置")
        return self._request(
            "POST",
            "/api/v1/knowledge-bases",
            payload={
                "name": name,
                "description": description,
                "type": "document",
                "embedding_model_id": self.config.embedding_model_id,
                "summary_model_id": self.config.chat_model_id,
                "chunking_config": {"chunk_size": 800, "chunk_overlap": 100},
                "indexing_strategy": {
                    "vector_enabled": True,
                    "keyword_enabled": True,
                    "wiki_enabled": wiki_enabled,
                    "graph_enabled": False,
                },
                "wiki_config": {
                    "synthesis_model_id": self.config.chat_model_id,
                    "extraction_granularity": "focused",
                    "max_pages_per_ingest": 8,
                    "ingest_map_parallel": 1,
                    "ingest_reduce_parallel": 1,
                    "ingest_max_inflight": 1,
                    "content_instructions": "使用简体中文整理正文，保留英文矿物及专业术语别名、原文引用和适用条件。",
                    "extraction_instructions": "优先整理矿物、岩石、蚀变、成矿、数据质量与方法概念；保留专业英文别名。",
                },
            },
        )

    def get_knowledge_base(self, kb_id: str) -> dict:
        return self._request("GET", f"/api/v1/knowledge-bases/{_part(kb_id)}")

    def delete_knowledge_base(self, kb_id: str) -> dict:
        return self._request("DELETE", f"/api/v1/knowledge-bases/{_part(kb_id)}")

    def upload_text(self, kb_id: str, *, title: str, content: str) -> dict:
        return self._request(
            "POST",
            f"/api/v1/knowledge-bases/{_part(kb_id)}/knowledge/manual",
            payload={
                "title": title,
                "content": content,
                "status": "publish",
                "channel": "api",
            },
        )

    def upload_file(
        self, kb_id: str, *, filename: str, file: BinaryIO, display_name: str = ""
    ) -> dict:
        if any(c in filename for c in '\r\n"/\\') or not filename:
            raise WeKnoraError("文件名无效", status=400)
        data = file.read(20 * 1024 * 1024 + 1)
        if len(data) > 20 * 1024 * 1024:
            raise WeKnoraError("知识文档不能超过20MB", status=400)
        boundary = "weknora-" + uuid4().hex
        display = ""
        if display_name:
            display = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="fileName"\r\n\r\n'
                f"{display_name[:240].replace(chr(0), '')}\r\n"
            )
        body = (
            (
                display
                + f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode("utf-8")
            + data
            + f"\r\n--{boundary}--\r\n".encode()
        )
        return self._request(
            "POST",
            f"/api/v1/knowledge-bases/{_part(kb_id)}/knowledge/file",
            body=body,
            content_type=f"multipart/form-data; boundary={boundary}",
            duplicate_kb_id=kb_id,
        )

    def get_document(self, document_id: str) -> dict:
        return self._request("GET", f"/api/v1/knowledge/{_part(document_id)}")

    def delete_document(self, document_id: str) -> dict:
        return self._request("DELETE", f"/api/v1/knowledge/{_part(document_id)}")

    def reparse_document(self, document_id: str) -> dict:
        return self._request(
            "POST", f"/api/v1/knowledge/{_part(document_id)}/reparse", payload={}
        )

    def hybrid_search(
        self,
        kb_id: str,
        query: str,
        *,
        limit: int = 8,
        document_ids: list[str] | None = None,
        vector_only: bool = False,
    ) -> list:
        # Empty allow-list means no authorized documents, never an unrestricted query.
        if document_ids == []:
            return []
        payload = {
            "query_text": query,
            "match_count": max(1, min(20, limit)),
            "vector_threshold": 0.2,
            "keyword_threshold": 0,
            "disable_keywords_match": vector_only,
            "disable_vector_match": False,
            "skip_context_enrichment": True,
        }
        if document_ids is not None:
            payload["knowledge_ids"] = document_ids
        result = self._request(
            "POST",
            f"/api/v1/knowledge-bases/{_part(kb_id)}/hybrid-search",
            payload=payload,
        )
        if not isinstance(result, list):
            raise WeKnoraError("知识检索返回了无法识别的响应")
        return result

    def wiki_pages(
        self, kb_id: str, *, query: str = "", page: int = 1, page_size: int = 30
    ) -> dict:
        return self._request(
            "GET",
            f"/api/v1/knowledgebase/{_part(kb_id)}/wiki/pages",
            query={
                "query": query,
                "page": max(1, page),
                "page_size": max(1, min(100, page_size)),
            },
        )

    def wiki_page(self, kb_id: str, slug: str) -> dict:
        return self._request(
            "GET", f"/api/v1/knowledgebase/{_part(kb_id)}/wiki/pages/{_part(slug)}"
        )

    def wiki_stats(self, kb_id: str) -> dict:
        return self._request("GET", f"/api/v1/knowledgebase/{_part(kb_id)}/wiki/stats")

    def wiki_graph(self, kb_id: str, *, center: str = "", limit: int = 80) -> dict:
        query = {
            "mode": "ego" if center else "overview",
            "limit": max(1, min(200, limit)),
        }
        if center:
            query.update({"center": center, "depth": 1})
        return self._request(
            "GET", f"/api/v1/knowledgebase/{_part(kb_id)}/wiki/graph", query=query
        )
