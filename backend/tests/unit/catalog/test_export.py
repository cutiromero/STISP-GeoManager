import csv
import io
import json
import tempfile
import zipfile
from pathlib import Path

from django.test import SimpleTestCase

from apps.catalog.export import (
    ExportError,
    export_layers_zip,
    export_vector_attributes_csv,
    export_vector_geojson,
    safe_filename,
    validate_epsg,
    write_cutline,
)


class SafeFilenameTests(SimpleTestCase):
    def test_removes_special_characters(self):
        self.assertEqual(safe_filename("test file!@#"), "test-file")

    def test_preserves_chinese_characters(self):
        self.assertEqual(safe_filename("测试数据"), "测试数据")

    def test_preserves_dots_and_hyphens(self):
        self.assertEqual(safe_filename("test-file_v2.shp"), "test-file_v2.shp")

    def test_limits_length_to_80(self):
        long_name = "a" * 100
        result = safe_filename(long_name)
        self.assertLessEqual(len(result), 80)

    def test_returns_layer_for_empty_result(self):
        self.assertEqual(safe_filename("!@#$%^&*"), "layer")

    def test_strips_leading_trailing_dots_and_hyphens(self):
        self.assertEqual(safe_filename(".-test-."), "test")


class ValidateEpsgTests(SimpleTestCase):
    def test_validates_valid_epsg(self):
        self.assertEqual(validate_epsg(4326), 4326)
        self.assertEqual(validate_epsg(3857), 3857)

    def test_rejects_low_epsg(self):
        with self.assertRaises(Exception):
            validate_epsg(100)

    def test_rejects_high_epsg(self):
        with self.assertRaises(Exception):
            validate_epsg(1000000)

    def test_rejects_non_numeric(self):
        with self.assertRaises(Exception):
            validate_epsg("invalid")


class ExportVectorGeojsonTests(SimpleTestCase):
    def test_exports_empty_feature_collection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test_export.geojson"
            export_vector_geojson(
                {"type": "FeatureCollection", "features": []},
                4326,
                output,
            )
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["type"], "FeatureCollection")
            self.assertEqual(data["features"], [])

    def test_rejects_invalid_geojson(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test_export.geojson"
            with self.assertRaises(ExportError):
                export_vector_geojson("not a dict", 4326, output)

    def test_rejects_non_feature_collection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test_export.geojson"
            with self.assertRaises(ExportError):
                export_vector_geojson({"type": "Feature"}, 4326, output)


class ExportVectorAttributesCsvTests(SimpleTestCase):
    def test_exports_feature_properties(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "name": "样点一",
                        "height": 4.2,
                        "tags": ["a", "b"],
                    },
                    "geometry": {"type": "Point", "coordinates": [80, 40]},
                },
                {
                    "type": "Feature",
                    "properties": {"name": "样点二", "health": None},
                    "geometry": {"type": "Point", "coordinates": [81, 41]},
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "attributes.csv"
            export_vector_attributes_csv(geojson, output)

            rows = list(
                csv.DictReader(io.StringIO(output.read_text(encoding="utf-8-sig")))
            )

        self.assertEqual(rows[0]["feature_index"], "1")
        self.assertEqual(rows[0]["name"], "样点一")
        self.assertEqual(rows[0]["height"], "4.2")
        self.assertEqual(rows[0]["tags"], '["a", "b"]')
        self.assertEqual(rows[1]["feature_index"], "2")
        self.assertEqual(rows[1]["name"], "样点二")
        self.assertEqual(rows[1]["health"], "")


class WriteCutlineTests(SimpleTestCase):
    def test_writes_valid_cutline(self):
        geometry = {
            "type": "Polygon",
            "coordinates": [[[80, 40], [80, 45], [85, 45], [85, 40], [80, 40]]],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = write_cutline(root, geometry)
            self.assertTrue(path.exists())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["type"], "FeatureCollection")
            self.assertEqual(len(data["features"]), 1)
            self.assertEqual(data["features"][0]["geometry"]["type"], "Polygon")

    def test_rejects_non_polygon_geometry(self):
        geometry = {"type": "Point", "coordinates": [80, 40]}
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaises(ExportError):
                write_cutline(root, geometry)

    def test_rejects_invalid_geometry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaises(ExportError):
                write_cutline(root, "not a dict")


class ExportLayersZipTests(SimpleTestCase):
    def test_rejects_empty_items(self):
        with self.assertRaises(ExportError):
            export_layers_zip([], 4326)

    def test_rejects_invalid_epsg_with_reproject(self):
        items = [
            {
                "layerType": "vector",
                "name": "test",
                "geojson": {"type": "FeatureCollection", "features": []},
            }
        ]
        with self.assertRaises(ExportError):
            export_layers_zip(items, 100, reproject=True)

    def test_exports_vector_layer(self):
        items = [
            {
                "layerType": "vector",
                "name": "测试图层",
                "geojson": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"name": "test"},
                            "geometry": {"type": "Point", "coordinates": [80, 40]},
                        }
                    ],
                },
            }
        ]
        result = export_layers_zip(items, 4326, reproject=False)
        self.assertIsInstance(result, bytes)
        self.assertTrue(len(result) > 0)
        with zipfile.ZipFile(io.BytesIO(result)) as archive:
            names = archive.namelist()
            attributes_name = next(
                name for name in names if name.endswith("-attributes.csv")
            )
            self.assertTrue(any(name.endswith(".geojson") for name in names))
            rows = list(
                csv.DictReader(
                    io.StringIO(archive.read(attributes_name).decode("utf-8-sig"))
                )
            )
            self.assertEqual(rows[0]["name"], "test")

    def test_rejects_unsupported_layer_type(self):
        items = [{"layerType": "unknown", "name": "test"}]
        with self.assertRaises(ExportError):
            export_layers_zip(items, 4326, reproject=False)
