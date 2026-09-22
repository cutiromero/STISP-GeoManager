import io
import tempfile
from pathlib import Path

from django.test import SimpleTestCase
from PIL import Image

from apps.raster.services.constants import WEB_MERCATOR_HALF_WORLD
from apps.raster.services.tile_pyramid import (
    build_atomic_mbtiles_pyramid,
    native_web_mercator_max_zoom,
    read_mbtiles_metadata,
    read_mbtiles_tile,
    tile_pyramid_spec,
    tile_range_for_bounds,
)


class TilePyramidGeometryTests(SimpleTestCase):
    def test_native_zoom_matches_real_lucc_resolution(self):
        metadata = {
            "geoTransform": [11878970.0, 2.5135294664, 0, 4464624.0, 0, -2.5135294664]
        }

        self.assertEqual(native_web_mercator_max_zoom(metadata), 16)

    def test_real_lucc_extent_has_bounded_complete_pyramid(self):
        metadata = {
            "geoTransform": [11878970.0, 2.5135294664, 0, 4464624.0, 0, -2.5135294664]
        }
        bounds = [11878970.324, 4440315.859, 11906988.637, 4464624.202]

        spec = tile_pyramid_spec(bounds, metadata)

        self.assertEqual(spec.max_zoom, 16)
        self.assertEqual(spec.total_tiles, 2575)

    def test_world_bounds_cover_all_four_z1_tiles(self):
        half = WEB_MERCATOR_HALF_WORLD
        self.assertEqual(
            tile_range_for_bounds([-half, -half, half, half], 1), (0, 1, 0, 1)
        )


class AtomicMbtilesPyramidTests(SimpleTestCase):
    def test_builds_complete_xyz_pyramid_and_reuses_it(self):
        half = WEB_MERCATOR_HALF_WORLD
        metadata = {
            "geoTransform": [
                -half,
                (half * 2 / 256) / 2,
                0,
                half,
                0,
                -(half * 2 / 256) / 2,
            ]
        }
        colors = {
            (0, 0): (255, 0, 0, 255),
            (1, 0): (0, 255, 0, 255),
            (0, 1): (0, 0, 255, 255),
            (1, 1): (255, 255, 0, 255),
        }

        def render_native(_z: int, x: int, y: int) -> bytes:
            output = io.BytesIO()
            Image.new("RGBA", (256, 256), colors[(x, y)]).save(output, "PNG")
            return output.getvalue()

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "style.mbtiles"
            progress_updates: list[tuple[int, int, int]] = []
            first = build_atomic_mbtiles_pyramid(
                target,
                style_hash="style-a",
                bounds=[-half, -half, half, half],
                metadata=metadata,
                render_native_tile=render_native,
                progress=lambda done, total, zoom: progress_updates.append(
                    (done, total, zoom)
                ),
            )
            second = build_atomic_mbtiles_pyramid(
                target,
                style_hash="style-a",
                bounds=[-half, -half, half, half],
                metadata=metadata,
                render_native_tile=lambda _z, _x, _y: self.fail(
                    "complete pyramid should be reused"
                ),
            )

            self.assertFalse(first.reused)
            self.assertTrue(second.reused)
            self.assertEqual(first.total_tiles, 5)
            self.assertEqual(progress_updates[0], (1, 5, 1))
            self.assertEqual(progress_updates[-1], (5, 5, 0))
            self.assertEqual(read_mbtiles_metadata(target)["complete"], "1")
            for (x, y), color in colors.items():
                tile = read_mbtiles_tile(target, 1, x, y)
                self.assertIsNotNone(tile)
                with Image.open(io.BytesIO(tile or b"")) as image:
                    self.assertEqual(image.getpixel((128, 128)), color)

            parent = read_mbtiles_tile(target, 0, 0, 0)
            self.assertIsNotNone(parent)
            with Image.open(io.BytesIO(parent or b"")) as image:
                self.assertEqual(
                    {color for _count, color in image.getcolors(maxcolors=16) or []},
                    set(colors.values()),
                )
