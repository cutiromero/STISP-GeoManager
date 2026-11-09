"""Build provenance, identity fences and bounded public build retention."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import json

from django.conf import settings
from django.http import Http404, JsonResponse
from django.test import RequestFactory, override_settings
import pytest

from apps.core import client_build, frontend_assets as assets
from apps.core.browser_sessions import SESSION_KEY
from apps.core.middleware import ApiContextMiddleware


@pytest.fixture
def history(tmp_path):
    config = replace(settings.PROJECT_CONFIG, app_data=tmp_path / "app")
    with override_settings(PROJECT_CONFIG=config):
        yield assets.history_root()
    assets._cached_index.cache_clear()


def build(tmp_path, key, *, shared=True):
    root = tmp_path / key
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(
        f'<script type="module" src="/static/assets/{key}.js"></script>'
    )
    (root / "assets" / f"{key}.js").write_text(f'import "./vendor-shared.js"; // {key}')
    if shared:
        (root / "assets/vendor-shared.js").write_text("export const n = 1;")
    return root


def content(name):
    response = assets.historical_asset(
        RequestFactory().get("/static/assets/" + name), name
    )
    try:
        value = b"".join(response.streaming_content)
        return value, response
    finally:
        response.close()


@pytest.mark.efficiency
def test_retains_complete_old_builds_and_reuses_signed_index(history, tmp_path):
    old, new = build(tmp_path, "old"), build(tmp_path, "new")
    assets.archive_assets(old, now=1)
    vendor = history / "files/vendor-shared.js"
    identity = assets.file_identity(vendor.stat())
    assets.archive_assets(new, now=2)
    assert assets.file_identity(vendor.stat()) == identity
    assert len(assets._index(history)["builds"]) == 2
    with patch.object(assets, "read_receipt", wraps=assets.read_receipt) as read:
        assert b"// old" in content("old.js")[0]
        assert b"// new" in content("new.js")[0]
        assert b"export const" in content("vendor-shared.js")[0]
        assert read.call_count == 1
    response = content("old.js")[1]
    assert response["Content-Type"] == "application/javascript"
    assert response["X-STISP-Asset-History"] == "1"
    assert "immutable" in response["Cache-Control"]
    assert response["X-Content-Type-Options"] == "nosniff"


def test_public_history_rejects_unlisted_paths_tampering_and_collisions(
    history, tmp_path
):
    root = build(tmp_path, "old")
    assets.archive_assets(root)
    for name in ("../index.json", "/etc/passwd", "x\\y", "missing.js"):
        with pytest.raises(Http404):
            content(name)
    path = history / "files/old.js"
    path.chmod(0o644)
    path.write_text("altered")
    with pytest.raises(Http404):
        content("old.js")
    # Re-archiving restores this public cache from the intact published build.
    assets.archive_assets(root)
    assert b"// old" in content("old.js")[0]
    (root / "assets/old.js").write_text("collision")
    with pytest.raises(ValueError, match="collision"):
        assets.archive_assets(root)
    assert b"// old" in content("old.js")[0]
    envelope = json.loads((history / "index.json").read_text())
    envelope["value"]["files"]["forged.js"] = envelope["value"]["files"]["old.js"]
    (history / "index.json").write_text(json.dumps(envelope))
    with pytest.raises(Http404):
        content("old.js")


def test_history_prunes_entire_build_dependency_sets(history, tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "MAXIMUM_BUILDS", 2)
    for i in range(3):
        assets.archive_assets(build(tmp_path, f"build{i}"), now=100 + i)
    assert not (history / "files/build0.js").exists()
    assert (history / "files/vendor-shared.js").exists()
    assert b"build1" in content("build1.js")[0]
    assets.archive_assets(build(tmp_path, "latest"), now=100 + 15 * 86400)
    assert len(assets._index(history)["builds"]) == 1
    assert not (history / "files/build1.js").exists()


def test_history_enforces_budget_and_rejects_source_symlinks(
    history, tmp_path, monkeypatch
):
    monkeypatch.setattr(assets, "MAXIMUM_BYTES", 1)
    root = build(tmp_path, "large")
    with pytest.raises(ValueError, match="budget"):
        assets.archive_assets(root)
    assert not (history / "index.json").exists()
    monkeypatch.setattr(assets, "MAXIMUM_BYTES", 512 * 1024**2)
    (root / "assets/link.js").symlink_to(root / "assets/large.js")
    with pytest.raises(ValueError, match="symlinks"):
        assets.archive_assets(root)


@pytest.mark.efficiency
def test_build_entry_reads_once_per_file_version(tmp_path):
    root = build(tmp_path, "first")
    client_build._entry.cache_clear()
    with override_settings(FRONTEND_DIST=root, STATIC_ROOT=tmp_path / "static"):
        with patch.object(
            Path, "read_text", autospec=True, side_effect=Path.read_text
        ) as read:
            assert client_build.current_entry() == "/static/assets/first.js"
            assert client_build.current_entry() == "/static/assets/first.js"
            assert read.call_count == 1
            (root / "index.html").write_text(
                '<script type="module" src="/static/assets/second.js"></script>'
            )
            assert client_build.current_entry() == "/static/assets/second.js"
            assert read.call_count == 2
    client_build._entry.cache_clear()


@pytest.mark.parametrize(
    "expected,status,calls", [("", 200, 1), ("a" * 32, 200, 1), ("b" * 32, 409, 0)]
)
def test_identity_fence_stops_view_before_wrong_account_access(expected, status, calls):
    request = RequestFactory().post("/api/private/", HTTP_X_STISP_SESSION=expected)
    request.user = SimpleNamespace(is_authenticated=True)
    request.session = {SESSION_KEY: {"familyId": "a" * 32}}
    view = Mock(return_value=JsonResponse({"detail": "ok"}))
    with patch(
        "apps.core.middleware.current_entry", return_value="/static/assets/new.js"
    ):
        response = ApiContextMiddleware(view)(request)
    assert response.status_code == status
    assert view.call_count == calls
    assert response["X-STISP-Session"] == "a" * 32
    assert response["X-STISP-Build"] == "/static/assets/new.js"
    assert len(response["X-Request-Id"]) == 24
    assert "no-store" in response["Cache-Control"]


def test_optional_fence_does_not_authenticate_anonymous_or_override_cache():
    request = RequestFactory().get("/api/tile/", HTTP_X_STISP_SESSION="a" * 32)
    request.user = SimpleNamespace(is_authenticated=False)
    request.session = {}
    view = Mock(return_value=JsonResponse({"detail": "请先登录"}, status=401))
    response = ApiContextMiddleware(view)(request)
    assert response.status_code == 401
    assert "X-STISP-Session" not in response
    view.return_value = JsonResponse({"detail": "public tile"})
    view.return_value["Cache-Control"] = "public, max-age=60"
    assert ApiContextMiddleware(view)(request)["Cache-Control"] == "public, max-age=60"


def test_current_static_wins_and_missing_assets_fall_back_to_history(history, tmp_path):
    from django.test import Client

    old = build(tmp_path, "older")
    assets.archive_assets(old)
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "assets/current.js").write_text("// current public bundle")
    with override_settings(STATIC_ROOT=static, WHITENOISE_AUTOREFRESH=False):
        client = Client()
        current = client.get("/static/assets/current.js")
        assert current.status_code == 200
        assert b"current public bundle" in b"".join(current.streaming_content)
        current.close()
        old_response = client.get("/static/assets/older.js")
        assert old_response.status_code == 200
        assert old_response["X-STISP-Asset-History"] == "1"
        old_response.close()
        assert client.get("/static/assets/missing.js").status_code == 404
