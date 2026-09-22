from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings

from apps.core.config import load_project_config
from apps.raster.services.importer import (
    normalize_import_resampling,
    store_uploaded_source_file,
)


class UploadedRasterStorageTests(SimpleTestCase):
    def test_categorical_import_always_uses_nearest_neighbor(self):
        self.assertEqual(
            normalize_import_resampling("categorical", "bilinear"), "nearest"
        )
        self.assertEqual(
            normalize_import_resampling("categorical", "cubic"), "nearest"
        )
        self.assertEqual(
            normalize_import_resampling("continuous", "bilinear"), "bilinear"
        )

    def test_store_uploaded_source_file_uses_identifier_without_original_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self._config(Path(tmpdir))
            uploaded_file = SimpleUploadedFile(
                "poplar-ndvi-2026.tif",
                b"fake raster bytes",
                content_type="image/tiff",
            )

            with (
                override_settings(PROJECT_CONFIG=config),
                patch(
                    "apps.raster.services.importer.gdalinfo_json",
                    return_value={"size": [256, 128]},
                ),
            ):
                path = store_uploaded_source_file(uploaded_file)

        self.assertRegex(path.name, r"^[0-9a-f]{32}\.tif$")
        self.assertNotIn("poplar", path.name)
        self.assertNotIn("ndvi", path.name)

    def _config(self, root: Path):
        app_root = root / "app"
        research_root = root / "research"
        config_path = root / "app.test.toml"
        config_path.write_text(
            f"""
[runtime]
debug = true
allowed_hosts = ["*"]
csrf_trusted_origins = []
waitress_host = "127.0.0.1"
waitress_port = 8000
waitress_threads = 1
disable_catalog_startup_scan = true
disable_raster_startup_scan = true

[application.system]
name = "test"
allow_registration = true

[application.storage]
app_data = "{app_root.as_posix()}"
research_data_root = "{research_root.as_posix()}"

[application.map]
default_center = [80.0, 41.5]
default_zoom = 4.5
default_basemap = "osm"
mapbox_access_token = ""

[application.limits]
upload_max_mb = 512
query_result_limit = 30000
max_raster_side_pixels = 10000

[application.raster]
symbolizer_timeout_seconds = 120
""".strip(),
            encoding="utf-8",
        )
        return load_project_config(
            config_path, program_root=Path("/tmp/huyang-program")
        )
