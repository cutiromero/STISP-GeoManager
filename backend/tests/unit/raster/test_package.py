import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings

from apps.core.config import load_project_config
from apps.raster.services.exceptions import RasterImportError
from apps.raster.services.package import (
    infer_raster_kind,
    preview_uploaded_raster_package,
    store_uploaded_raster_package,
)


class RasterPackageTests(SimpleTestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_envi_dat_requires_matching_header(self):
        with self.assertRaisesRegex(RasterImportError, "HDR|头文件"):
            preview_uploaded_raster_package(
                [SimpleUploadedFile("scene.dat", b"data")], "scene.dat"
            )

    def test_envi_dat_and_header_are_previewed_as_one_package(self):
        info = self._gdalinfo(driver="ENVI", band_count=4)
        with (
            override_settings(PROJECT_CONFIG=self._config()),
            patch("apps.raster.services.package.gdalinfo_json", return_value=info),
        ):
            result = preview_uploaded_raster_package(
                [
                    SimpleUploadedFile("scene.dat", b"data"),
                    SimpleUploadedFile("scene.hdr", b"ENVI\n"),
                ],
                "scene.dat",
            )

        self.assertEqual(result["sourceFormat"], "ENVI")
        self.assertEqual(result["primaryFileName"], "scene.dat")
        self.assertEqual(
            {item["role"] for item in result["files"]}, {"primary", "header"}
        )

    def test_vrt_rejects_missing_referenced_file(self):
        vrt = b"""<VRTDataset rasterXSize="1" rasterYSize="1">
          <VRTRasterBand dataType="Byte" band="1">
            <SimpleSource><SourceFilename relativeToVRT="1">source.tif</SourceFilename></SimpleSource>
          </VRTRasterBand>
        </VRTDataset>"""
        with override_settings(PROJECT_CONFIG=self._config()):
            with self.assertRaisesRegex(RasterImportError, "source.tif"):
                preview_uploaded_raster_package(
                    [SimpleUploadedFile("scene.vrt", vrt)], "scene.vrt"
                )

    def test_worldview_eight_band_preview_uses_natural_color_preset(self):
        info = self._gdalinfo(driver="GTiff", band_count=8)
        with (
            override_settings(PROJECT_CONFIG=self._config()),
            patch("apps.raster.services.package.gdalinfo_json", return_value=info),
        ):
            result = preview_uploaded_raster_package(
                [SimpleUploadedFile("Tarim_worldview_1.tif", b"tif")]
            )

        self.assertEqual(result["defaultRules"]["bands"], [5, 3, 2])

    def test_worldview_preview_uses_observed_band_range_for_stretch(self):
        info = self._gdalinfo(driver="GTiff", band_count=8)
        info["bands"][4].update({"min": 36, "max": 92})
        with (
            override_settings(PROJECT_CONFIG=self._config()),
            patch("apps.raster.services.package.gdalinfo_json", return_value=info),
        ):
            result = preview_uploaded_raster_package(
                [SimpleUploadedFile("Tarim_worldview_1.tif", b"tif")]
            )

        self.assertEqual(
            result["defaultRules"]["stretch"]["perBand"]["5"],
            {"min": 36.0, "max": 92.0},
        )

    def test_lucc_class_codes_are_detected_and_used_as_default_legend(self):
        info = self._gdalinfo(driver="GTiff", band_count=1)
        info["metadata"] = {
            "": {
                "CLASS_CODES": "1=裸地/草地;2=耕地;4=林地;5=水体;6=建筑;8=道路",
                "NODATA_VALUE": "255",
            }
        }
        with (
            override_settings(PROJECT_CONFIG=self._config()),
            patch("apps.raster.services.package.gdalinfo_json", return_value=info),
        ):
            result = preview_uploaded_raster_package(
                [SimpleUploadedFile("hjyt_tile_r1_c1.tif", b"tif")]
            )

        self.assertEqual(infer_raster_kind(info), "categorical")
        self.assertEqual(result["rasterKind"], "categorical")
        self.assertEqual(result["resampling"], "nearest")
        self.assertEqual(result["defaultRules"]["mode"], "unique")
        self.assertFalse(result["defaultRules"]["stretch"]["enabled"])
        self.assertEqual(
            [item["value"] for item in result["defaultRules"]["uniqueValues"]],
            [1, 2, 4, 5, 6, 8],
        )
        self.assertEqual(
            [item["label"] for item in result["defaultRules"]["uniqueValues"]],
            ["裸地/草地", "耕地", "林地", "水体", "建筑", "道路"],
        )
        colors = {
            item["label"]: item["color"]
            for item in result["defaultRules"]["uniqueValues"]
        }
        self.assertEqual(colors["林地"], "#2f7d62")
        self.assertEqual(colors["水体"], "#3b79b7")
        self.assertEqual(colors["道路"], "#5b5b5b")

    def test_store_package_uses_uuid_directory_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self._config(Path(tmpdir))
            info = self._gdalinfo(driver="GTiff", band_count=3)
            with (
                override_settings(PROJECT_CONFIG=config),
                patch("apps.raster.services.package.gdalinfo_json", return_value=info),
            ):
                primary_path, manifest, checksum = store_uploaded_raster_package(
                    [SimpleUploadedFile("scene.tif", b"tif-bytes")]
                )

            self.assertEqual(primary_path.name, "scene.tif")
            self.assertRegex(primary_path.parent.name, r"^[0-9a-f]{32}$")
            self.assertTrue((primary_path.parent / "manifest.json").exists())
            self.assertEqual(manifest[0]["role"], "primary")
            self.assertEqual(len(checksum), 64)

    def _config(self, root: Path | None = None):
        root = root or Path(self.tempdir.name)
        config_path = root / "app.toml"
        config_path.write_text(
            f"""
[runtime]
debug = true
allowed_hosts = ["localhost"]
csrf_trusted_origins = []
waitress_host = "127.0.0.1"
waitress_port = 8000
waitress_threads = 2
disable_catalog_startup_scan = true
disable_raster_startup_scan = true

[application.system]
name = "test"
allow_registration = false

[application.storage]
app_data = "{(root / "app").as_posix()}"
research_data_root = "{(root / "research").as_posix()}"

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
        return load_project_config(config_path, Path(__file__).resolve().parents[4])

    @staticmethod
    def _gdalinfo(driver: str, band_count: int):
        return {
            "driverShortName": driver,
            "size": [512, 512],
            "coordinateSystem": {"wkt": "EPSG:32645"},
            "stac": {"proj:epsg": 32645},
            "wgs84Extent": {
                "coordinates": [
                    [
                        [88.0, 40.1],
                        [88.0, 40.0],
                        [88.1, 40.0],
                        [88.1, 40.1],
                        [88.0, 40.1],
                    ]
                ]
            },
            "bands": [
                {"band": index, "type": "Byte", "colorInterpretation": "Undefined"}
                for index in range(1, band_count + 1)
            ],
        }
