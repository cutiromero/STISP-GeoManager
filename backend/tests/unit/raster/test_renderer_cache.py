from unittest.mock import patch

from django.test import SimpleTestCase

from apps.raster.services import renderer


class RasterRendererCacheTests(SimpleTestCase):
    def setUp(self):
        renderer._clear_renderer_caches()

    def tearDown(self):
        renderer._clear_renderer_caches()

    def test_style_cache_is_lru_bounded(self):
        with patch.object(renderer, "TILE_STYLE_CACHE_MAX_ENTRIES", 2):
            renderer._remember_tile_style((1, "a"), {"rules": "a"}, now=1)
            renderer._remember_tile_style((1, "b"), {"rules": "b"}, now=2)
            self.assertEqual(
                renderer._get_tile_style((1, "a"), now=3), {"rules": "a"}
            )
            renderer._remember_tile_style((1, "c"), {"rules": "c"}, now=4)

        self.assertEqual(list(renderer._TILE_STYLES), [(1, "a"), (1, "c")])
        self.assertIsNone(renderer._get_tile_style((1, "b"), now=4))

    def test_style_cache_expires_entries_after_ttl(self):
        with patch.object(renderer, "TILE_STYLE_CACHE_TTL_SECONDS", 5):
            renderer._remember_tile_style(
                (7, "expired"), {"rules": "old"}, now=10
            )
            cached = renderer._get_tile_style((7, "expired"), now=15)

        self.assertIsNone(cached)
        self.assertFalse(renderer._TILE_STYLES)

    def test_png_byte_cache_is_limited_to_128_tiles(self):
        self.assertEqual(renderer._render_xyz_tile_cached.cache_info().maxsize, 128)
