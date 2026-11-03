from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.raster.services import renderer, tile_singleflight


class TileSingleflightTests(SimpleTestCase):
    def test_concurrent_cold_tile_renders_once_and_releases_slots(self):
        renderer._clear_renderer_caches()
        calls = []
        barrier = threading.Barrier(6)

        def render(*args):
            calls.append(True)
            time.sleep(0.05)
            return b"png"

        def request():
            barrier.wait(timeout=5)
            return renderer.render_xyz_tile(1, "style", 1, 0, 0)

        with TemporaryDirectory() as temp:
            path = Path(temp) / "image.tif"
            path.write_bytes(b"raster")
            dataset = SimpleNamespace(
                processed_relative_path="image.tif",
                raster_kind="continuous",
                bounds_3857=[],
            )
            try:
                with (
                    patch.object(
                        renderer.RasterDataset.objects, "get", return_value=dataset
                    ),
                    patch.object(renderer, "raster_processed_path", return_value=path),
                    patch.object(
                        renderer, "_validated_tile_style", return_value={"rules": {}}
                    ),
                    patch("rasterio.open", return_value=MagicMock()),
                    patch.object(
                        renderer, "_render_open_raster_tile", side_effect=render
                    ),
                    ThreadPoolExecutor(max_workers=6) as pool,
                ):
                    futures = [pool.submit(request) for _ in range(6)]
                    self.assertEqual(
                        [f.result(timeout=5) for f in futures], [b"png"] * 6
                    )
                    self.assertEqual(len(calls), 1)
                    renderer.render_xyz_tile(1, "style", 1, 0, 0)
                    self.assertEqual(len(calls), 1)
                    renderer.render_xyz_tile(1, "style", 1, 1, 0)
                    self.assertEqual(len(calls), 2)
            finally:
                renderer._clear_renderer_caches()
        self.assertFalse(tile_singleflight._pending)

    def test_different_tiles_run_in_parallel_and_failure_frees_slot(self):
        barrier = threading.Barrier(2)

        def request(key):
            with tile_singleflight.tile_render_slot(key):
                barrier.wait(timeout=5)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(request, key) for key in ("a", "b")]
            for future in futures:
                future.result(timeout=5)
        with self.assertRaisesRegex(ValueError, "render failed"):
            with tile_singleflight.tile_render_slot("failed"):
                raise ValueError("render failed")
        with tile_singleflight.tile_render_slot("failed"):
            pass
        self.assertFalse(tile_singleflight._pending)
