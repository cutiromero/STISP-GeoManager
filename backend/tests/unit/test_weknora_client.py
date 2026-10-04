import io
import json
from urllib.error import HTTPError, URLError

import pytest

from apps.knowledge.weknora_client import (
    WeKnoraClient,
    WeKnoraConfig,
    WeKnoraError,
    configured_weknora,
)


class FakeResponse(io.BytesIO):
    pass


class FakeOpener:
    def __init__(self, value):
        self.value = value
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        if isinstance(self.value, Exception):
            raise self.value
        return FakeResponse(json.dumps(self.value).encode())


def client(value):
    result = WeKnoraClient(WeKnoraConfig(enabled=True, api_key="secret"))
    result._opener = FakeOpener(value)
    return result


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org",
        "http://localhost:18080",
        "http://127.0.0.1:18080/x",
        "http://user:password@127.0.0.1:18080",
        "http://127.0.0.1:18080?x=1",
        "http://10.0.0.1:18080",
        "http://127.0.0.1:bad",
    ],
)
def test_only_literal_loopback_deployment_url(url):
    with pytest.raises(WeKnoraError):
        WeKnoraClient(WeKnoraConfig(base_url=url))


def test_search_scopes_and_unwraps_official_response():
    c = client(
        {"success": True, "data": [{"knowledge_id": "doc", "content": "地质知识"}]}
    )
    assert (
        c.hybrid_search("kb", "矿物共生", document_ids=["doc"])[0]["knowledge_id"]
        == "doc"
    )
    request = c._opener.requests[0]
    payload = json.loads(request.data)
    assert payload["knowledge_ids"] == ["doc"]
    assert "knowledge_base_ids" not in payload
    assert payload["disable_vector_match"] is False
    assert request.get_header("X-api-key") == "secret"
    assert request.full_url.endswith("/knowledge-bases/kb/hybrid-search")


def test_empty_allowlist_does_not_query_upstream():
    c = client([])
    assert c.hybrid_search("kb", "secret", document_ids=[]) == []
    assert c._opener.requests == []


def test_raw_wiki_response_and_encoded_slug():
    c = client({"slug": "矿物/霞石", "content": "test", "source_refs": ["doc"]})
    assert c.wiki_page("kb", "矿物/霞石")["source_refs"] == ["doc"]
    assert "%2F" in c._opener.requests[0].full_url


def test_wiki_stats_preserve_real_pending_state():
    c = client({"total_pages": 3, "is_active": True, "pending_tasks": 2})
    assert c.wiki_stats("kb")["pending_tasks"] == 2


@pytest.mark.parametrize(
    "error",
    [
        URLError("http://127.0.0.1/private?secret=key"),
        HTTPError("http://127.0.0.1", 500, "secret", {}, None),
        HTTPError("http://127.0.0.1", 302, "redirect secret", {}, None),
    ],
)
def test_error_never_exposes_secret_or_upstream_body(error):
    c = client(error)
    with pytest.raises(WeKnoraError) as caught:
        c.get_document("doc")
    assert "secret" not in str(caught.value)
    assert "127.0.0.1" not in str(caught.value)


def test_response_bound():
    c = WeKnoraClient(
        WeKnoraConfig(enabled=True, api_key="secret", max_response_bytes=1024)
    )
    c._opener = FakeOpener({"content": "x" * 2000})
    with pytest.raises(WeKnoraError, match="响应过大"):
        c.wiki_page("kb", "page")


def test_file_headers_cannot_be_injected():
    c = client({})
    with pytest.raises(WeKnoraError, match="文件名"):
        c.upload_file("kb", filename='data.txt"\r\nattack', file=io.BytesIO(b"data"))
    assert c._opener.requests == []


def test_disabled_service_makes_no_request():
    c = WeKnoraClient(WeKnoraConfig())
    c._opener = FakeOpener({})
    with pytest.raises(WeKnoraError, match="尚未启用"):
        c.health()
    assert not c._opener.requests


def test_deployment_config_reads_secret_file(settings, tmp_path):
    path = tmp_path / "weknora-key"
    path.write_text("private-key\n")
    settings.WEKNORA_CONFIG = {
        "enabled": True,
        "api_key_file": str(path),
        "embedding_model_id": "embedding",
    }
    cfg = configured_weknora()
    assert cfg.api_key == "private-key"
    assert "private-key" not in repr(cfg)


def test_created_library_uses_official_wiki_strategy():
    c = WeKnoraClient(
        WeKnoraConfig(
            enabled=True,
            api_key="secret",
            embedding_model_id="embed",
            chat_model_id="chat",
        )
    )
    c._opener = FakeOpener({"success": True, "data": {"id": "kb"}})
    assert c.create_knowledge_base("地学知识")["id"] == "kb"
    payload = json.loads(c._opener.requests[0].data)
    assert payload["indexing_strategy"]["wiki_enabled"] is True
    assert payload["wiki_config"]["synthesis_model_id"] == "chat"
    assert payload["indexing_strategy"]["graph_enabled"] is False


@pytest.mark.parametrize("same_library", [True, False])
def test_file_retry_reuses_only_same_library_duplicate(same_library):
    body = {
        "code": "duplicate_file",
        "data": {
            "id": "existing-document",
            "knowledge_base_id": "kb" if same_library else "other-kb",
        },
    }
    error = HTTPError(
        "http://127.0.0.1", 409, "Conflict", {}, io.BytesIO(json.dumps(body).encode())
    )
    c = client(error)
    if same_library:
        assert (
            c.upload_file("kb", filename="source.md", file=io.BytesIO(b"source"))["id"]
            == "existing-document"
        )
    else:
        with pytest.raises(WeKnoraError):
            c.upload_file("kb", filename="source.md", file=io.BytesIO(b"source"))
