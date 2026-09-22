import json
import sqlite3
import tempfile
from dataclasses import replace
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings

from apps.catalog.models import DataResource
from apps.core.storage import gene_data_path, table_data_path


class NonGeographicAnalysisApiTests(TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.temporary.name)
        self.config = replace(
            settings.PROJECT_CONFIG,
            app_data=root / "app",
            research_data_root=root / "research",
        )
        self.override = override_settings(PROJECT_CONFIG=self.config)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.temporary.cleanup)

        self.user = get_user_model().objects.create_user(
            username="nongeo-researcher", password="pass12345"
        )
        grant(
            self.user,
            ("core", "browse_data"),
            ("core", "query_data"),
        )
        self.client.force_login(self.user)
        self.sqlite_path = table_data_path("data.sqlite")
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.sqlite_path) as connection:
            connection.execute(
                'CREATE TABLE "survey_alpha" (sample_id TEXT, species TEXT, height REAL)'
            )
            connection.executemany(
                'INSERT INTO "survey_alpha" VALUES (?, ?, ?)',
                [
                    ("A-1", "胡杨", 12.5),
                    ("A-2", "柽柳", 5.2),
                    ("A-3", "胡杨", 18.0),
                ],
            )
            connection.execute(
                'CREATE TABLE "survey_beta" (marker TEXT, allele_count INTEGER)'
            )
            connection.executemany(
                'INSERT INTO "survey_beta" VALUES (?, ?)',
                [("SSR-1", 2), ("SSR-2", 4)],
            )
            connection.execute(
                """
                CREATE TABLE data_columns (
                    table_name TEXT NOT NULL,
                    column_name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (table_name, column_name)
                )
                """
            )
            connection.execute(
                "INSERT INTO data_columns VALUES (?, ?, ?)",
                ("survey_alpha", "height", "植株高度（米）"),
            )

        self.alpha = self._table_resource(
            "真实样地表", "survey-alpha", "survey_alpha", 3
        )
        self.beta = self._table_resource(
            "真实分子标记表", "survey-beta", "survey_beta", 2
        )

    def test_different_resources_return_their_own_real_rows_and_statistics(self):
        alpha = self.client.get(
            f"/api/catalog/resources/{self.alpha.id}/nongeo-analysis/"
        )
        beta = self.client.get(
            f"/api/catalog/resources/{self.beta.id}/nongeo-analysis/"
        )

        self.assertEqual(alpha.status_code, 200)
        self.assertEqual(beta.status_code, 200)
        alpha_payload = alpha.json()
        beta_payload = beta.json()
        self.assertEqual(alpha_payload["summary"]["rowCount"], 3)
        self.assertEqual(beta_payload["summary"]["rowCount"], 2)
        self.assertEqual(
            {field["name"] for field in alpha_payload["fields"]},
            {"sample_id", "species", "height"},
        )
        self.assertEqual(
            {field["name"] for field in beta_payload["fields"]},
            {"marker", "allele_count"},
        )
        self.assertEqual(alpha_payload["tablePreview"]["rows"][0]["sample_id"], "A-1")
        self.assertEqual(beta_payload["tablePreview"]["rows"][0]["marker"], "SSR-1")
        height = next(
            field for field in alpha_payload["fields"] if field["name"] == "height"
        )
        self.assertEqual(height["description"], "植株高度（米）")
        self.assertEqual(height["min"], 5.2)
        self.assertEqual(height["max"], 18.0)

    def test_query_is_paginated_and_sorts_only_allowlisted_fields(self):
        response = self.client.post(
            f"/api/catalog/resources/{self.alpha.id}/nongeo-query/",
            data=json.dumps(
                {
                    "limit": 2,
                    "offset": 0,
                    "sortField": "height",
                    "sortDirection": "desc",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["totalCount"], 3)
        self.assertEqual(payload["returnedCount"], 2)
        self.assertEqual([row["height"] for row in payload["rows"]], [18.0, 12.5])

        rejected = self.client.post(
            f"/api/catalog/resources/{self.alpha.id}/nongeo-query/",
            data=json.dumps({"sortField": 'height"; DROP TABLE survey_alpha;--'}),
            content_type="application/json",
        )
        self.assertEqual(rejected.status_code, 400)
        with sqlite3.connect(self.sqlite_path) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM survey_alpha").fetchone()[0],
                3,
            )

    def test_default_project_nongeographic_analysis_is_public(self):
        restricted_group = Group.objects.create(name="受限非地理角色")
        restricted = DataResource.objects.create(
            name="受限表",
            code="restricted-nongeo",
            data_type=DataResource.DataType.TABLE,
            file_format="SQLITE",
            storage_path="survey_alpha",
            status=DataResource.Status.ACTIVE,
        )
        restricted.access_groups.add(restricted_group)

        hidden = self.client.get(
            f"/api/catalog/resources/{restricted.id}/nongeo-analysis/"
        )
        self.assertEqual(hidden.status_code, 200)

        self.user.user_permissions.clear()
        grant(self.user, ("core", "browse_data"))
        denied = self.client.get(
            f"/api/catalog/resources/{self.alpha.id}/nongeo-analysis/"
        )
        self.assertEqual(denied.status_code, 200)

    def test_fasta_analysis_uses_actual_sequences(self):
        path = gene_data_path("poplar.fasta")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            ">seq-a first\nACGTGGCC\n>seq-b second\nAAAA\n",
            encoding="utf-8",
        )
        resource = DataResource.objects.create(
            name="真实 FASTA",
            code="real-fasta",
            data_type=DataResource.DataType.GENE,
            file_format="FASTA",
            storage_path="gene/poplar.fasta",
            maintainer=self.user,
            status=DataResource.Status.ACTIVE,
        )

        response = self.client.get(
            f"/api/catalog/resources/{resource.id}/nongeo-analysis/"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["rowCount"], 2)
        self.assertEqual(
            [row["sequenceId"] for row in payload["tablePreview"]["rows"]],
            ["seq-a", "seq-b"],
        )
        self.assertEqual(payload["tablePreview"]["rows"][0]["gcContent"], 0.75)

    def _table_resource(self, name: str, code: str, table: str, count: int):
        return DataResource.objects.create(
            name=name,
            code=code,
            data_type=DataResource.DataType.TABLE,
            file_format="SQLITE",
            storage_path=table,
            maintainer=self.user,
            item_count=count,
            status=DataResource.Status.ACTIVE,
        )


def grant(user, *specs: tuple[str, str]) -> None:
    for app_label, codename in specs:
        permission = Permission.objects.get(
            content_type__app_label=app_label,
            codename=codename,
        )
        user.user_permissions.add(permission)
