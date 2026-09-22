import pandas as pd
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from io import BytesIO
from types import SimpleNamespace
from unittest import mock

from apps.catalog.importer import (
    ImportDataError,
    _included_columns,
    _metadata_map,
    infer_coordinate_columns,
    normalize_dataframe,
    normalize_coordinate_columns,
    preview_uploaded_table,
    read_uploaded_table,
    validate_import_table_name,
    validate_uploaded_table,
)
from apps.catalog.vector_importer import (
    _validate_upload_size as validate_vector_upload_size,
)


class ImporterUnitTests(SimpleTestCase):
    def test_normalize_dataframe_trims_values_and_deduplicates_columns(self):
        df = pd.DataFrame(
            [[" 样点A ", "", None]],
            columns=["name", "name", ""],
        )

        normalized = normalize_dataframe(df)

        self.assertEqual(list(normalized.columns), ["name", "name_2", "column_3"])
        self.assertEqual(normalized.iloc[0].tolist(), ["样点A", "", ""])

    def test_infer_coordinate_columns_detects_chinese_aliases(self):
        df = pd.DataFrame(
            {
                "样点": ["A"],
                "经度": ["87.600"],
                "纬度": ["43.800"],
            }
        )

        longitude, latitude = infer_coordinate_columns(df)

        self.assertEqual(longitude, "经度")
        self.assertEqual(latitude, "纬度")

    def test_infer_coordinate_columns_detects_compact_dms_values(self):
        df = pd.DataFrame(
            {
                "样点": ["A", "B"],
                "经度": ["79480913", "79480955"],
                "纬度": ["40212444", "40212437"],
            }
        )

        longitude, latitude = infer_coordinate_columns(df)

        self.assertEqual(longitude, "经度")
        self.assertEqual(latitude, "纬度")

    def test_validate_accepts_compact_dms_coordinates(self):
        result = validate_uploaded_table(
            self._csv_file(
                "survey.csv",
                "name,lon,lat\nA,79480913,40212444\nB,79480955,40212437\n",
            ),
            {
                "importMode": "geographic",
                "longitudeColumn": "lon",
                "latitudeColumn": "lat",
            },
        )

        self.assertEqual(result["coordinateStats"]["validRows"], 2)
        self.assertEqual(result["validationIssues"], [])

    def test_normalize_coordinate_columns_converts_dms_to_decimal_degrees(self):
        df = pd.DataFrame({"lon": ["79480913"], "lat": ["40°21′24.44″"]})

        normalized = normalize_coordinate_columns(
            df, longitude_column="lon", latitude_column="lat"
        )

        self.assertEqual(normalized.loc[0, "lon"], "79.80253611")
        self.assertEqual(normalized.loc[0, "lat"], "40.35678889")

    def test_dms_seconds_suffix_is_not_treated_as_south_direction(self):
        df = pd.DataFrame({"lon": ["79d48m09.13s"], "lat": ["40d21m24.44s"]})

        normalized = normalize_coordinate_columns(
            df, longitude_column="lon", latitude_column="lat"
        )

        self.assertEqual(normalized.loc[0, "lon"], "79.80253611")
        self.assertEqual(normalized.loc[0, "lat"], "40.35678889")

    def test_dms_supports_chinese_direction_prefixes(self):
        df = pd.DataFrame(
            {"lon": ["东经79度48分09.13秒"], "lat": ["北纬40度21分24.44秒"]}
        )

        normalized = normalize_coordinate_columns(
            df, longitude_column="lon", latitude_column="lat"
        )

        self.assertEqual(normalized.loc[0, "lon"], "79.80253611")
        self.assertEqual(normalized.loc[0, "lat"], "40.35678889")

    def test_preview_lists_excel_sheets_and_reads_selected_sheet(self):
        workbook = self._excel_file(
            "multi.xlsx",
            {
                "first": pd.DataFrame({"name": ["A"], "value": ["1"]}),
                "points": pd.DataFrame(
                    {"name": ["B"], "经度": ["79480913"], "纬度": ["40212444"]}
                ),
            },
        )

        with mock.patch(
            "apps.catalog.importer.duplicate_target_for_display_name",
            return_value=None,
        ):
            preview = preview_uploaded_table(workbook, sheet_name="points")

        self.assertEqual(preview["activeSheetName"], "points")
        self.assertEqual(
            [sheet["name"] for sheet in preview["sheets"]], ["first", "points"]
        )
        self.assertEqual(preview["rowCount"], 1)
        self.assertTrue(preview["detected"]["isGeographic"])
        self.assertEqual(preview["detected"]["longitudeColumn"], "经度")

    def test_read_uploaded_table_reads_requested_excel_sheet(self):
        workbook = self._excel_file(
            "multi.xlsx",
            {
                "first": pd.DataFrame({"name": ["A"]}),
                "second": pd.DataFrame({"name": ["B"], "value": ["2"]}),
            },
        )

        df = read_uploaded_table(workbook, sheet_name="second")

        self.assertEqual(df.iloc[0]["name"], "B")
        self.assertEqual(list(df.columns), ["name", "value"])

    def test_validate_table_mode_skips_coordinate_validation(self):
        result = validate_uploaded_table(
            self._csv_file("survey.csv", "name,lon,lat\nA,181.000,\n"),
            {"importMode": "table"},
        )

        self.assertEqual(
            result,
            {
                "coordinateStats": None,
                "validationIssues": [],
                "duplicateTarget": None,
            },
        )

    def test_validate_rejects_unknown_import_mode(self):
        with self.assertRaisesRegex(
            ImportDataError, "导入方式必须是 geographic 或 table"
        ):
            validate_uploaded_table(
                self._csv_file("survey.csv", "name\nA\n"),
                {"importMode": "unsupported"},
            )

    def test_included_columns_keep_required_coordinate_columns(self):
        selected = _included_columns(
            ["name"],
            ["name", "lon", "lat", "note"],
            required_columns={"lon", "lat"},
        )

        self.assertEqual(selected, ["name", "lon", "lat"])

    def test_included_columns_reject_unknown_columns(self):
        with self.assertRaisesRegex(ImportDataError, "上传字段不存在：missing"):
            _included_columns(["name", "missing"], ["name", "value"])

    def test_metadata_map_rejects_invalid_json(self):
        with self.assertRaisesRegex(ImportDataError, "字段元数据不是有效 JSON"):
            _metadata_map("{bad-json", {"name"})

    def test_metadata_map_ignores_unknown_columns(self):
        metadata = _metadata_map({"name": "样点名称", "extra": "忽略"}, {"name"})

        self.assertEqual(metadata, {"name": "样点名称"})

    def test_validate_import_table_name_rejects_unsafe_names(self):
        unsafe_names = ["1bad", "has-dash", "含中文", "a" * 64]

        for table_name in unsafe_names:
            with self.subTest(table_name=table_name):
                with self.assertRaises(ImportDataError):
                    validate_import_table_name(table_name)

    def test_read_uploaded_table_rejects_empty_file(self):
        with self.assertRaisesRegex(ImportDataError, "上传文件为空"):
            read_uploaded_table(self._csv_file("empty.csv", ""))

    def test_read_uploaded_table_rejects_unsupported_extension(self):
        with self.assertRaisesRegex(ImportDataError, "仅支持 .csv、.xls、.xlsx 文件"):
            read_uploaded_table(
                SimpleUploadedFile(
                    "survey.txt", b"name\nA\n", content_type="text/plain"
                )
            )

    def test_table_parser_applies_independent_memory_safety_limit(self):
        uploaded = SimpleUploadedFile(
            "large.csv",
            b"x" * (1024 * 1024 + 1),
            content_type="text/csv",
        )

        with (
            mock.patch("apps.catalog.importer.runtime_upload_max_mb", return_value=64),
            mock.patch("apps.catalog.importer.MAX_TABLE_PARSE_UPLOAD_MB", 1),
        ):
            with self.assertRaisesRegex(ImportDataError, "平台上传大小限制"):
                read_uploaded_table(uploaded)

    def test_vector_import_keeps_independent_memory_safety_limit(self):
        uploaded = SimpleNamespace(size=120 * 1024 * 1024 + 1)

        with mock.patch(
            "apps.catalog.vector_importer.runtime_upload_max_mb",
            return_value=1024,
        ):
            with self.assertRaisesRegex(ImportDataError, "不能超过 120 MB"):
                validate_vector_upload_size(uploaded)

    def _csv_file(self, name: str, content: str) -> SimpleUploadedFile:
        return SimpleUploadedFile(
            name, content.encode("utf-8"), content_type="text/csv"
        )

    def _excel_file(
        self, name: str, sheets: dict[str, pd.DataFrame]
    ) -> SimpleUploadedFile:
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            for sheet_name, df in sheets.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        return SimpleUploadedFile(
            name,
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
