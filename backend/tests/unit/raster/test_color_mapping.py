import numpy as np
from django.test import SimpleTestCase

from apps.raster.services.color_mapping import (
    array_to_rgba,
    hex_to_rgba,
    palette_array,
    scale_array,
)


class HexToRgbaTests(SimpleTestCase):
    def test_six_digit_hex(self):
        self.assertEqual(hex_to_rgba("#ff0000"), (255, 0, 0, 255))

    def test_eight_digit_hex(self):
        self.assertEqual(hex_to_rgba("#ff000080"), (255, 0, 0, 128))

    def test_no_hash(self):
        self.assertEqual(hex_to_rgba("00ff00"), (0, 255, 0, 255))

    def test_invalid_hex_returns_black(self):
        self.assertEqual(hex_to_rgba("zzz"), (0, 0, 0, 255))


class PaletteArrayTests(SimpleTestCase):
    def test_known_palette(self):
        arr = palette_array("viridis")
        self.assertEqual(arr.shape[0], 4)
        self.assertEqual(arr.shape[1], 3)

    def test_unknown_palette_falls_back_to_poplar(self):
        arr = palette_array("nonexistent")
        self.assertEqual(arr.shape[0], 3)


class ScaleArrayTests(SimpleTestCase):
    def test_scales_to_0_255(self):
        values = np.array([0, 50, 100], dtype=np.float32)
        metadata = {"bands": [{"band": 1, "min": 0, "max": 100}]}
        rules = {"stretch": {"enabled": True, "perBand": {"1": {"min": 0, "max": 100}}}}
        result = scale_array(values, rules, metadata, 1)
        self.assertEqual(result.dtype, np.uint8)
        self.assertEqual(result[0], 0)
        self.assertEqual(result[2], 255)

    def test_disabled_stretch_clips(self):
        values = np.array([0, 128, 300], dtype=np.float32)
        rules = {"stretch": {"enabled": False}}
        result = scale_array(values, rules, {}, 1)
        self.assertEqual(result[2], 255)


class ArrayToRgbaTests(SimpleTestCase):
    def test_gray_mode(self):
        data = np.ma.MaskedArray(np.array([[0, 128]], dtype=np.float32), mask=False)
        rules = {
            "mode": "gray",
            "bands": [1],
            "stretch": {"enabled": True, "perBand": {"1": {"min": 0, "max": 255}}},
        }
        metadata = {"bands": [{"band": 1}]}
        result = array_to_rgba(data, rules, metadata)
        self.assertEqual(result.shape, (1, 2, 4))
        self.assertEqual(result[0, 0, 0], result[0, 0, 1])

    def test_rgb_mode(self):
        data = np.ma.MaskedArray(
            np.array([[[100, 150]], [[100, 150]], [[100, 150]]], dtype=np.float32),
            mask=False,
        )
        rules = {
            "mode": "rgb",
            "bands": [1, 2, 3],
            "stretch": {
                "enabled": True,
                "perBand": {
                    "1": {"min": 0, "max": 255},
                    "2": {"min": 0, "max": 255},
                    "3": {"min": 0, "max": 255},
                },
            },
        }
        metadata = {"bands": [{"band": 1}, {"band": 2}, {"band": 3}]}
        result = array_to_rgba(data, rules, metadata)
        self.assertEqual(result.shape, (1, 2, 4))

    def test_rgb_mode_uses_alpha_band_when_present(self):
        data = np.ma.MaskedArray(
            np.array([[[100]], [[100]], [[100]], [[128]]], dtype=np.float32),
            mask=False,
        )
        rules = {
            "mode": "rgb",
            "bands": [1, 2, 3],
            "alphaBand": 4,
            "stretch": {
                "enabled": True,
                "perBand": {
                    "1": {"min": 0, "max": 255},
                    "2": {"min": 0, "max": 255},
                    "3": {"min": 0, "max": 255},
                },
            },
        }
        metadata = {"bands": [{"band": 1}, {"band": 2}, {"band": 3}, {"band": 4}]}
        result = array_to_rgba(data, rules, metadata)
        self.assertEqual(result[0, 0, 3], 128)

    def test_masked_pixels_become_transparent(self):
        data = np.ma.MaskedArray(np.array([[100]], dtype=np.float32), mask=True)
        rules = {
            "mode": "gray",
            "bands": [1],
            "stretch": {"enabled": True, "perBand": {"1": {"min": 0, "max": 255}}},
        }
        metadata = {"bands": [{"band": 1}]}
        result = array_to_rgba(data, rules, metadata)
        self.assertEqual(result[0, 0, 3], 0)

    def test_rgb_all_zero_warp_border_becomes_transparent(self):
        data = np.ma.MaskedArray(
            np.array([[[0, 100]], [[0, 100]], [[0, 100]]], dtype=np.float32),
            mask=False,
        )
        rules = {
            "mode": "rgb",
            "bands": [1, 2, 3],
            "nodata": {"enabled": True},
            "stretch": {
                "enabled": True,
                "perBand": {
                    "1": {"min": 0, "max": 255},
                    "2": {"min": 0, "max": 255},
                    "3": {"min": 0, "max": 255},
                },
            },
        }
        metadata = {"bands": [{"band": 1}, {"band": 2}, {"band": 3}]}

        result = array_to_rgba(data, rules, metadata)

        self.assertEqual(result[0, 0, 3], 0)
        self.assertEqual(result[0, 1, 3], 255)
