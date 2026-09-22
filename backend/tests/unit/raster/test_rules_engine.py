from django.test import SimpleTestCase

from apps.raster.services.rules_engine import (
    band_min_max,
    is_integer_band,
    default_raster_rules,
    normalize_rules,
    normalize_stretch_bands,
    normalize_unique_values,
    output_source_bands,
    read_source_bands,
    stretch_min_max,
)
from apps.raster.services.exceptions import RasterRenderError


def _single_band_metadata(min_val=0, max_val=255):
    return {"bands": [{"band": 1, "min": min_val, "max": max_val}]}


def _three_band_metadata():
    return {
        "bands": [
            {"band": 1, "min": 10, "max": 200},
            {"band": 2, "min": 20, "max": 210},
            {"band": 3, "min": 30, "max": 220},
        ]
    }


class BandMinMaxTests(SimpleTestCase):
    def test_returns_min_max_from_band(self):
        minimum, maximum = band_min_max(_single_band_metadata(5, 100), 1)
        self.assertEqual(minimum, 5.0)
        self.assertEqual(maximum, 100.0)

    def test_reads_alternate_gdal_minimum_maximum_keys(self):
        minimum, maximum = band_min_max(
            {"bands": [{"band": 1, "minimum": 7, "maximum": 91}]}, 1
        )
        self.assertEqual(minimum, 7.0)
        self.assertEqual(maximum, 91.0)

    def test_returns_defaults_for_missing_band(self):
        minimum, maximum = band_min_max({"bands": []}, 1)
        self.assertEqual(minimum, 0.0)
        self.assertEqual(maximum, 255.0)

    def test_uses_fallback_metadata(self):
        metadata = {"bands": [{"band": 1}]}
        fallback = _single_band_metadata(10, 200)
        minimum, maximum = band_min_max(metadata, 1, fallback)
        self.assertEqual(minimum, 10.0)
        self.assertEqual(maximum, 200.0)

    def test_ensures_max_greater_than_min(self):
        minimum, maximum = band_min_max(_single_band_metadata(50, 50), 1)
        self.assertEqual(maximum, minimum + 1.0)


class DefaultRasterRulesTests(SimpleTestCase):
    def test_single_band_produces_gray_mode(self):
        rules = default_raster_rules(_single_band_metadata())
        self.assertEqual(rules["mode"], "gray")
        self.assertEqual(rules["bands"], [1])
        self.assertEqual(rules["uniqueValues"], [])

    def test_three_bands_produces_rgb_mode(self):
        rules = default_raster_rules(_three_band_metadata())
        self.assertEqual(rules["mode"], "rgb")
        self.assertEqual(rules["bands"], [1, 2, 3])

    def test_two_bands_fills_third(self):
        metadata = {
            "bands": [
                {"band": 1, "min": 0, "max": 100},
                {"band": 2, "min": 0, "max": 100},
            ]
        }
        rules = default_raster_rules(metadata)
        self.assertEqual(rules["mode"], "rgb")
        self.assertEqual(rules["bands"], [1, 2, 2])

    def test_source_statistics_can_avoid_zero_warp_border_stretch(self):
        source = _single_band_metadata(36, 92)
        processed = _single_band_metadata(0, 90)

        rules = default_raster_rules(source, processed)

        self.assertEqual(
            rules["stretch"]["perBand"]["1"],
            {"min": 36.0, "max": 92.0},
        )


class NormalizeRulesTests(SimpleTestCase):
    def test_validates_mode(self):
        with self.assertRaises(RasterRenderError):
            normalize_rules({"mode": "invalid"}, _single_band_metadata())

    def test_clamps_band_indices(self):
        rules = normalize_rules({"bands": [0, 99]}, _three_band_metadata())
        self.assertEqual(rules["bands"][0], 1)
        self.assertEqual(rules["bands"][1], 3)

    def test_rgb_mode_requires_three_bands(self):
        rules = normalize_rules({"mode": "rgb", "bands": [1]}, _three_band_metadata())
        self.assertEqual(len(rules["bands"]), 3)

    def test_normalizes_alpha_and_nodata(self):
        rules = normalize_rules(
            {"mode": "rgb", "alphaBand": 99, "nodata": {"enabled": False}},
            _three_band_metadata(),
        )
        self.assertEqual(rules["alphaBand"], 3)
        self.assertFalse(rules["nodata"]["enabled"])


class OutputSourceBandsTests(SimpleTestCase):
    def test_rgb_returns_three_bands(self):
        rules = {"mode": "rgb", "bands": [1, 2, 3], "alphaBand": 4}
        self.assertEqual(output_source_bands(rules), [1, 2, 3])
        self.assertEqual(read_source_bands(rules), [1, 2, 3, 4])

    def test_gray_returns_single_band(self):
        self.assertEqual(output_source_bands({"mode": "gray", "bands": [2]}), [2])


class StretchMinMaxTests(SimpleTestCase):
    def test_reads_per_band_values(self):
        rules = {"stretch": {"perBand": {"1": {"min": 10, "max": 200}}}}
        minimum, maximum = stretch_min_max(rules, _single_band_metadata(), 1)
        self.assertEqual(minimum, 10.0)
        self.assertEqual(maximum, 200.0)

    def test_falls_back_to_metadata(self):
        rules = {"stretch": {}}
        minimum, maximum = stretch_min_max(rules, _single_band_metadata(5, 100), 1)
        self.assertEqual(minimum, 5.0)
        self.assertEqual(maximum, 100.0)


class NormalizeStretchBandsTests(SimpleTestCase):
    def test_fills_all_bands(self):
        result = normalize_stretch_bands(None, _three_band_metadata())
        self.assertEqual(set(result.keys()), {"1", "2", "3"})

    def test_ensures_max_greater_than_min(self):
        result = normalize_stretch_bands(
            {"1": {"min": 50, "max": 50}}, _single_band_metadata()
        )
        self.assertGreater(result["1"]["max"], result["1"]["min"])


class NormalizeUniqueValuesTests(SimpleTestCase):
    def test_returns_default_for_empty_input(self):
        result = normalize_unique_values(None, _single_band_metadata(0, 5))
        self.assertEqual(result, [])

    def test_normalizes_provided_values(self):
        raw = [{"value": 1, "color": "#ff0000", "label": "A"}]
        result = normalize_unique_values(raw, _single_band_metadata())
        self.assertEqual(result[0]["value"], 1)
        self.assertEqual(result[0]["color"], "#ff0000")


class IntegerBandTests(SimpleTestCase):
    def test_detects_integer_band(self):
        self.assertTrue(is_integer_band({"bands": [{"band": 1, "type": "UInt16"}]}, 1))

    def test_rejects_float_band(self):
        self.assertFalse(
            is_integer_band({"bands": [{"band": 1, "type": "Float32"}]}, 1)
        )
