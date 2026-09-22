from io import BytesIO
from unittest.mock import patch

import pytest
from PIL import Image

from apps.core.config import load_project_config
from apps.core.map_thumbnail import ThumbnailTileError
from .test_api import _minimal_config_text


@pytest.fixture
def tile_environment(settings, tmp_path):
    config_path = tmp_path / "app.toml"
    config_path.write_text(
        _minimal_config_text(tmp_path / "app", tmp_path / "research"), encoding="utf-8"
    )
    settings.PROJECT_CONFIG = load_project_config(
        config_path, program_root=tmp_path / "program"
    )
    image = BytesIO()
    Image.new("RGB", (256, 256), "#346c8c").save(image, "PNG")
    return image.getvalue()


def test_export_rejects_missing_imagery_instead_of_generating_a_placeholder(
    client, tile_environment
):
    with (
        patch(
            "apps.core.map_thumbnail.fetch_tile",
            side_effect=ThumbnailTileError("unavailable upstream with secret URL"),
        ) as fetch,
        patch("apps.core.map_thumbnail.generated_local_tile") as placeholder,
    ):
        response = client.get("/api/map/thumbnail-tiles/3/4/2.png?purpose=export")
    assert response.status_code == 503
    assert response["Cache-Control"] == "no-store"
    assert response["Retry-After"] == "2"
    assert "制图底图服务暂时不可用" in response.json()["detail"]
    assert "secret" not in response.json()["detail"]
    assert fetch.call_args.kwargs["timeout"] == 10
    placeholder.assert_not_called()


def test_thumbnail_placeholder_does_not_poison_export_cache_and_export_recovers(
    client, tile_environment
):
    url = "/api/map/thumbnail-tiles/3/4/2.png"
    with patch(
        "apps.core.map_thumbnail.fetch_tile", side_effect=ThumbnailTileError("offline")
    ) as fetch:
        thumbnail = client.get(url)
        assert thumbnail.status_code == 200
        assert thumbnail["Cache-Control"] == "public, max-age=60"
        assert fetch.call_args.kwargs["timeout"] == 4
        assert client.get(url + "?purpose=export").status_code == 503

    with patch(
        "apps.core.map_thumbnail.fetch_tile",
        return_value=(tile_environment, "image/png"),
    ) as fetch:
        recovered = client.get(url + "?purpose=export")
        assert recovered.status_code == 200
        assert recovered.content == tile_environment
        assert recovered["Cache-Control"] == "public, max-age=86400"
        assert client.get(url + "?purpose=export").content == tile_environment
        fetch.assert_called_once()

    with patch(
        "apps.core.map_thumbnail.fetch_tile", side_effect=ThumbnailTileError("offline")
    ) as fetch:
        assert client.get(url + "?purpose=export").content == tile_environment
        fetch.assert_not_called()


@pytest.mark.parametrize("purpose", ["invalid", "", "EXPORT"])
def test_invalid_tile_purpose_rejected_before_upstream_access(client, purpose):
    with patch("apps.core.map_thumbnail.fetch_tile") as fetch:
        response = client.get(f"/api/map/thumbnail-tiles/3/4/2.png?purpose={purpose}")
        assert response.status_code == 400
        assert "detail" in response.json()
        fetch.assert_not_called()
