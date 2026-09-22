from django.test import SimpleTestCase

from apps.raster.services.geo_utils import (
    bounds_4326_from_gdalinfo,
    bounds_from_gdalinfo,
    image_coordinates_from_gdalinfo,
    intersects_bounds,
    style_hash_for,
    tile_bounds_3857,
    transparent_png,
)


class BoundsFromGdalinfoTests(SimpleTestCase):
    def test_returns_bounding_box(self):
        metadata = {
            "cornerCoordinates": {
                "upperLeft": [100, 50],
                "lowerLeft": [100, 40],
                "lowerRight": [110, 40],
                "upperRight": [110, 50],
            }
        }
        result = bounds_from_gdalinfo(metadata)
        self.assertEqual(result, [100, 40, 110, 50])

    def test_returns_empty_for_missing_corners(self):
        self.assertEqual(bounds_from_gdalinfo({}), [])


class Bounds4326FromGdalinfoTests(SimpleTestCase):
    def test_returns_lonlat_bounds(self):
        metadata = {
            "wgs84Extent": {
                "coordinates": [[[80, 40], [80, 45], [85, 45], [85, 40], [80, 40]]],
            }
        }
        result = bounds_4326_from_gdalinfo(metadata)
        self.assertEqual(result, [80, 40, 85, 45])

    def test_returns_empty_for_missing_extent(self):
        self.assertEqual(bounds_4326_from_gdalinfo({}), [])


class ImageCoordinatesFromGdalinfoTests(SimpleTestCase):
    def test_returns_corner_order(self):
        metadata = {
            "wgs84Extent": {
                "coordinates": [[[80, 45], [80, 40], [85, 40], [85, 45], [80, 45]]],
            }
        }
        result = image_coordinates_from_gdalinfo(metadata)
        self.assertEqual(result, [[80, 45], [85, 45], [85, 40], [80, 40]])

    def test_falls_back_to_bounds(self):
        metadata = {
            "wgs84Extent": {
                "coordinates": [[[80, 40], [80, 45], [85, 45], [85, 40]]],
            }
        }
        result = image_coordinates_from_gdalinfo(metadata)
        self.assertEqual(len(result), 4)


class TileBounds3857Tests(SimpleTestCase):
    def test_z0_covers_world(self):
        minx, miny, maxx, maxy = tile_bounds_3857(0, 0, 0)
        self.assertAlmostEqual(minx, -20037508.34, places=0)
        self.assertAlmostEqual(maxx, 20037508.34, places=0)

    def test_z1_has_four_tiles(self):
        bounds = [tile_bounds_3857(1, x, y) for x in range(2) for y in range(2)]
        self.assertEqual(len(bounds), 4)


class IntersectsBoundsTests(SimpleTestCase):
    def test_overlapping_bounds_intersect(self):
        bounds = (0.0, 0.0, 10.0, 10.0)
        self.assertTrue(
            intersects_bounds(
                bounds,
                type("B", (), {"left": 5, "right": 15, "bottom": 5, "top": 15})(),
            )
        )

    def test_non_overlapping_bounds_do_not_intersect(self):
        bounds = (0.0, 0.0, 10.0, 10.0)
        self.assertFalse(
            intersects_bounds(
                bounds,
                type("B", (), {"left": 20, "right": 30, "bottom": 20, "top": 30})(),
            )
        )

    def test_accepts_stored_bounds_array(self):
        bounds = (0.0, 0.0, 10.0, 10.0)
        self.assertTrue(intersects_bounds(bounds, [5, 5, 15, 15]))
        self.assertFalse(intersects_bounds(bounds, [20, 20, 30, 30]))


class TransparentPngTests(SimpleTestCase):
    def test_returns_valid_png_bytes(self):
        data = transparent_png()
        self.assertTrue(data[:4] == b"\x89PNG")


class StyleHashTests(SimpleTestCase):
    def test_style_hash_length_is_bounded(self):
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(suffix=".tif") as f:
            f.write(b"test")
            f.flush()
            path = Path(f.name)
            sh = style_hash_for(path, {"mode": "gray"})
            self.assertLessEqual(len(sh), 24)
