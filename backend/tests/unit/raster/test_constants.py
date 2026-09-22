from django.test import SimpleTestCase

from apps.raster.services.constants import (
    DEFAULT_TILE_SIZE,
    PALETTES,
    RASTER_EXTENSIONS,
    UNIQUE_COLORS,
    WEB_MERCATOR_HALF_WORLD,
)


class RasterExtensionsTests(SimpleTestCase):
    def test_contains_common_formats(self):
        self.assertIn(".tif", RASTER_EXTENSIONS)
        self.assertIn(".tiff", RASTER_EXTENSIONS)
        self.assertIn(".img", RASTER_EXTENSIONS)
        self.assertIn(".vrt", RASTER_EXTENSIONS)

    def test_is_set(self):
        self.assertIsInstance(RASTER_EXTENSIONS, set)


class WebMercatorHalfWorldTests(SimpleTestCase):
    def test_is_positive(self):
        self.assertGreater(WEB_MERCATOR_HALF_WORLD, 0)

    def test_is_approximately_20_million(self):
        self.assertAlmostEqual(WEB_MERCATOR_HALF_WORLD, 20037508.34, places=0)


class DefaultTileSizeTests(SimpleTestCase):
    def test_is_256(self):
        self.assertEqual(DEFAULT_TILE_SIZE, 256)


class PalettesTests(SimpleTestCase):
    def test_contains_poplar_palette(self):
        self.assertIn("poplar", PALETTES)
        self.assertGreater(len(PALETTES["poplar"]), 0)

    def test_contains_viridis_palette(self):
        self.assertIn("viridis", PALETTES)
        self.assertGreater(len(PALETTES["viridis"]), 0)

    def test_contains_terrain_palette(self):
        self.assertIn("terrain", PALETTES)
        self.assertGreater(len(PALETTES["terrain"]), 0)

    def test_contains_thermal_palette(self):
        self.assertIn("thermal", PALETTES)
        self.assertGreater(len(PALETTES["thermal"]), 0)

    def test_all_palette_colors_are_valid_hex(self):
        import re

        hex_pattern = re.compile(r"^#[0-9a-fA-F]{6}$")
        for name, colors in PALETTES.items():
            for color in colors:
                self.assertRegex(
                    color, hex_pattern, f"Palette '{name}' has invalid color: {color}"
                )


class UniqueColorsTests(SimpleTestCase):
    def test_contains_transparent_color(self):
        self.assertEqual(UNIQUE_COLORS[0], "#00000000")

    def test_has_multiple_colors(self):
        self.assertGreater(len(UNIQUE_COLORS), 5)

    def test_all_colors_are_valid_hex(self):
        import re

        hex_pattern = re.compile(r"^#[0-9a-fA-F]{6,8}$")
        for color in UNIQUE_COLORS:
            self.assertRegex(color, hex_pattern, f"Invalid color: {color}")
