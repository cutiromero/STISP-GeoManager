from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from apps.core.storage import (
    raster_processed_path,
    raster_source_path,
    raster_tile_pyramid_path,
)
from apps.raster.models import RasterDataset
from apps.raster.services import jobs as jobs_service
from apps.raster.services import renderer
from apps.raster.services.constants import WEB_MERCATOR_HALF_WORLD
from apps.raster.services.exceptions import RasterRenderError
from apps.raster.services.importer import (
    RASTER_PREPROCESSING_VERSION,
    scan_unprocessed_source_files,
)
from apps.raster.services.tile_pyramid import build_atomic_mbtiles_pyramid


def _project_config(root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        app_data=root / "app",
        research_data_root=root / "research",
    )


class LuccStaticRendererRegressionTests(TestCase):
    def setUp(self):
        renderer._clear_renderer_caches()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.settings_override = override_settings(
            PROJECT_CONFIG=_project_config(self.root)
        )
        self.settings_override.enable()

    def tearDown(self):
        renderer._clear_renderer_caches()
        self.settings_override.disable()
        self.temporary_directory.cleanup()

    def test_complete_static_mbtiles_hit_does_not_open_rasterio(self):
        dataset, _processed_path = self._create_categorical_dataset()
        result = renderer.register_tile_style(dataset, dataset.default_rules)
        style_hash = str(result["styleHash"])
        target = raster_tile_pyramid_path(
            dataset.id, style_hash, renderer.RASTER_RENDERER_VERSION
        )
        expected_tile = b"pre-rendered-lucc-tile"
        build_atomic_mbtiles_pyramid(
            target,
            style_hash=style_hash,
            bounds=dataset.bounds_3857,
            metadata=dataset.processed_gdalinfo,
            render_native_tile=lambda _z, _x, _y: expected_tile,
        )

        with patch("rasterio.open") as rasterio_open:
            tile = renderer.render_xyz_tile(dataset.id, style_hash, 0, 0, 0)

        self.assertEqual(tile, expected_tile)
        rasterio_open.assert_not_called()

    def test_missing_static_mbtiles_never_falls_back_to_dynamic_rendering(self):
        dataset, _processed_path = self._create_categorical_dataset()
        result = renderer.register_tile_style(dataset, dataset.default_rules)

        with (
            patch("rasterio.open") as rasterio_open,
            self.assertRaisesRegex(RasterRenderError, "尚未完整发布"),
        ):
            renderer.render_xyz_tile(
                dataset.id,
                str(result["styleHash"]),
                0,
                0,
                0,
            )

        rasterio_open.assert_not_called()

    def test_changed_cog_fingerprint_rejects_old_style_and_static_cache(self):
        dataset, processed_path = self._create_categorical_dataset()
        original_result = renderer.register_tile_style(dataset, dataset.default_rules)
        original_hash = str(original_result["styleHash"])
        original_stat = processed_path.stat()

        processed_path.write_bytes(b"changed-categorical-cog-content")
        os.utime(
            processed_path,
            ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns + 1_000_000_000),
        )
        changed_result = renderer.register_tile_style(dataset, dataset.default_rules)

        self.assertNotEqual(changed_result["styleHash"], original_hash)
        with (
            patch.object(
                renderer, "read_mbtiles_tile", return_value=b"stale-static-tile"
            ) as read_static_tile,
            patch("rasterio.open") as rasterio_open,
            self.assertRaisesRegex(RasterRenderError, "更新"),
        ):
            renderer.render_xyz_tile(dataset.id, original_hash, 0, 0, 0)

        read_static_tile.assert_not_called()
        rasterio_open.assert_not_called()

    def _create_categorical_dataset(self) -> tuple[RasterDataset, Path]:
        half_world = WEB_MERCATOR_HALF_WORLD
        metadata = {
            "bands": [{"band": 1, "type": "Byte", "min": 1, "max": 8}],
            "geoTransform": [
                -half_world,
                half_world * 2 / 256,
                0,
                half_world,
                0,
                -(half_world * 2 / 256),
            ],
        }
        rules = {
            "mode": "unique",
            "bands": [1],
            "uniqueValues": [{"value": 1, "label": "耕地", "color": "#f5d76eff"}],
            "alphaBand": "mask",
            "nodata": {"enabled": True},
        }
        processed_relative_path = "lucc-static.cog.tif"
        processed_path = raster_processed_path(processed_relative_path)
        processed_path.parent.mkdir(parents=True, exist_ok=True)
        processed_path.write_bytes(b"categorical-cog")
        dataset = RasterDataset.objects.create(
            name="LUCC 静态瓦片",
            code="lucc-static-renderer",
            source_relative_path="lucc-static.tif",
            processed_relative_path=processed_relative_path,
            raster_kind=RasterDataset.RasterKind.CATEGORICAL,
            resampling="nearest",
            processed_gdalinfo=metadata,
            default_rules=rules,
            bounds_3857=[-half_world, -half_world, half_world, half_world],
            band_count=1,
            status=RasterDataset.Status.READY,
        )
        return dataset, processed_path


class LuccRenderJobRegressionTests(SimpleTestCase):
    def setUp(self):
        with jobs_service._LOCK:
            jobs_service._JOBS.clear()
            jobs_service._LAST_PERSIST.clear()
        self.restart_reconciled = jobs_service._RESTART_RECONCILED
        jobs_service._RESTART_RECONCILED = True

    def tearDown(self):
        with jobs_service._LOCK:
            jobs_service._JOBS.clear()
            jobs_service._LAST_PERSIST.clear()
        jobs_service._RESTART_RECONCILED = self.restart_reconciled

    def test_categorical_render_job_is_not_ready_until_pyramid_build_returns(self):
        dataset = SimpleNamespace(
            raster_kind=RasterDataset.RasterKind.CATEGORICAL,
            default_rules={"mode": "unique", "bands": [1]},
        )
        queryset = SimpleNamespace(first=lambda: dataset)
        observed_states: list[tuple[str, str, object]] = []

        def build_pyramid(_dataset, _style_hash, *, progress):
            active_job = next(
                job for job in jobs_service._JOBS.values() if job.kind == "render"
            )
            observed_states.append(
                (active_job.status, active_job.stage, active_job.result)
            )
            progress(1, 2, 16)
            observed_states.append(
                (active_job.status, active_job.stage, active_job.result)
            )
            return SimpleNamespace(reused=False)

        with (
            patch.object(RasterDataset.objects, "filter", return_value=queryset),
            patch(
                "apps.raster.services.renderer.register_tile_style",
                return_value={"styleHash": "lucc-style"},
            ),
            patch(
                "apps.raster.services.renderer.build_static_xyz_tile_pyramid",
                side_effect=build_pyramid,
            ) as build_static_pyramid,
            patch.object(
                jobs_service,
                "_submit_job",
                side_effect=lambda _job, runner, **_kwargs: runner(),
            ),
        ):
            job = jobs_service.start_render_job(
                layer_id=None,
                dataset_id=7,
                rules=None,
            )

        self.assertEqual(
            observed_states,
            [
                ("running", "tile-pyramid", None),
                ("running", "tile-pyramid", None),
            ],
        )
        build_static_pyramid.assert_called_once()
        self.assertEqual(job.status, "ready")
        self.assertEqual(job.stage, "ready")
        self.assertEqual(job.result, {"styleHash": "lucc-style"})


class LuccStartupScanRegressionTests(TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.settings_override = override_settings(
            PROJECT_CONFIG=_project_config(self.root)
        )
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()
        self.temporary_directory.cleanup()

    def test_scan_rebuilds_legacy_categorical_cog_but_skips_current_version(self):
        legacy, legacy_source = self._create_scanned_dataset(
            "legacy-lucc", RASTER_PREPROCESSING_VERSION - 1
        )
        self._create_scanned_dataset("current-lucc", RASTER_PREPROCESSING_VERSION)

        with patch(
            "apps.raster.services.importer.import_raster_file",
            return_value=legacy,
        ) as import_raster_file:
            imported = scan_unprocessed_source_files()

        self.assertEqual(imported, [legacy])
        import_raster_file.assert_called_once()
        args, options = import_raster_file.call_args
        self.assertEqual(args, (legacy_source,))
        self.assertEqual(options["name"], legacy.name)
        self.assertEqual(options["raster_kind"], RasterDataset.RasterKind.CATEGORICAL)
        self.assertEqual(options["resampling"], "nearest")
        self.assertEqual(options["requested_default_rules"], legacy.default_rules)

    def _create_scanned_dataset(
        self, stem: str, preprocessing_version: int
    ) -> tuple[RasterDataset, Path]:
        source_relative_path = f"{stem}.tif"
        source_path = raster_source_path(source_relative_path)
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(b"source-categorical-raster")

        processed_relative_path = f"{stem}.cog.tif"
        processed_path = raster_processed_path(processed_relative_path)
        processed_path.parent.mkdir(parents=True, exist_ok=True)
        processed_path.write_bytes(b"processed-categorical-cog")

        dataset = RasterDataset.objects.create(
            name=stem,
            code=stem,
            source_relative_path=source_relative_path,
            processed_relative_path=processed_relative_path,
            raster_kind=RasterDataset.RasterKind.CATEGORICAL,
            resampling="nearest",
            processed_gdalinfo={
                "bands": [{"band": 1, "type": "Byte", "min": 1, "max": 8}],
                "geoManager": {
                    "preprocessingVersion": preprocessing_version,
                    "rasterKind": RasterDataset.RasterKind.CATEGORICAL,
                    "resampling": "nearest",
                },
            },
            default_rules={"mode": "unique", "bands": [1]},
            band_count=1,
            status=RasterDataset.Status.READY,
        )
        return dataset, source_path
