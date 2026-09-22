from __future__ import annotations

import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from apps.core.config import load_project_config
from apps.core.storage import (
    raster_metadata_path,
    raster_processed_path,
    raster_source_path,
)
from apps.raster.models import RasterDataset
from apps.raster.services.importer import (
    cleanup_uploaded_import_files,
    metadata_relative_path,
    processed_relative_path,
)


class UploadedRasterCleanupTests(TestCase):
    def test_cleanup_uploaded_import_files_removes_only_upload_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self._config(Path(tmpdir))
            with override_settings(PROJECT_CONFIG=config):
                source_relative = "uploaded/job-raster.tif"
                processed_relative = processed_relative_path(source_relative)
                source_metadata_relative = metadata_relative_path(
                    "source", source_relative
                )
                processed_metadata_relative = metadata_relative_path(
                    "preprocessed", processed_relative
                )
                source_path = raster_source_path(source_relative)
                processed_path = raster_processed_path(processed_relative)
                source_metadata_path = raster_metadata_path(source_metadata_relative)
                processed_metadata_path = raster_metadata_path(
                    processed_metadata_relative
                )
                for path in (
                    source_path,
                    processed_path,
                    source_metadata_path,
                    processed_metadata_path,
                ):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("partial", encoding="utf-8")
                RasterDataset.objects.create(
                    name="失败上传",
                    code="failed-upload",
                    source_relative_path=source_relative,
                    processed_relative_path=processed_relative,
                    source_metadata_relative_path=source_metadata_relative,
                    processed_metadata_relative_path=processed_metadata_relative,
                    status=RasterDataset.Status.FAILED,
                )

                cleanup_uploaded_import_files(source_path)

                self.assertFalse(source_path.exists())
                self.assertFalse(processed_path.exists())
                self.assertFalse(source_metadata_path.exists())
                self.assertFalse(processed_metadata_path.exists())
                self.assertFalse(
                    RasterDataset.objects.filter(
                        source_relative_path=source_relative
                    ).exists()
                )

    def test_cleanup_uploaded_import_files_ignores_non_uploaded_sources(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self._config(Path(tmpdir))
            with override_settings(PROJECT_CONFIG=config):
                source_path = raster_source_path("imported/existing.tif")
                source_path.parent.mkdir(parents=True, exist_ok=True)
                source_path.write_text("keep", encoding="utf-8")

                cleanup_uploaded_import_files(source_path)

                self.assertTrue(source_path.exists())
                self.assertEqual(source_path.read_text(encoding="utf-8"), "keep")

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
