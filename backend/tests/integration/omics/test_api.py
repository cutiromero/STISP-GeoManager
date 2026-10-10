from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from apps.catalog.models import DataResource
from apps.ecology.models import Site, Taxon
from apps.omics.models import GermplasmAccession


class DataSchemaSummaryApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="schema-user", password="pass12345"
        )

    def test_default_schema_summary_is_public(self):
        response = self.client.get("/api/data-schema/summary/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("catalogTree", response.json())

    def test_default_schema_summary_requires_no_extra_permission(self):
        self.client.force_login(self.user)

        response = self.client.get("/api/data-schema/summary/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("catalogTree", response.json())

    def test_schema_summary_returns_confirmed_domain_tree(self):
        grant(self.user, ("core", "browse_data"))
        self.client.force_login(self.user)

        response = self.client.get("/api/data-schema/summary/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["taxonomyVersion"], "2026.10")
        self.assertEqual(
            [item["code"] for item in payload["catalogTree"]],
            ["spatial", "non_spatial", "compute_results"],
        )
        self.assertEqual(
            [item["name"] for item in payload["catalogTree"]],
            ["地理数据", "非地理数据", "计算结果"],
        )
        self.assertTrue(all(item["selectable"] for item in payload["catalogTree"][:2]))
        self.assertFalse(payload["catalogTree"][2]["selectable"])
        self.assertTrue(
            any(
                entity["name"] == "GermplasmAccession" for entity in payload["entities"]
            )
        )
        self.assertTrue(
            any(entity["name"] == "VectorDataset" for entity in payload["entities"])
        )


class GermplasmAccessionApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="germplasm-user", password="pass12345"
        )
        grant(self.user, ("core", "browse_data"))
        self.client.force_login(self.user)

    def test_accession_list_returns_empty_page(self):
        response = self.client.get("/api/germplasm/accessions/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"items": [], "total": 0, "current": 1, "pageSize": 10},
        )

    def test_accession_list_filters_and_serializes_core_resource(self):
        accession = self.create_accession(
            accession_code="GA1",
            sample_code="GA1",
            is_core=True,
            resource_type="胡杨古树特异资源",
            site_name="阿克苏地区柯坪县",
            taxon_name="胡杨",
            scientific_name="Populus euphratica",
        )
        self.create_accession(
            accession_code="GB1",
            sample_code="GB1",
            is_core=False,
            resource_type="灰杨群体种质资源",
            site_name="巴音郭楞蒙古自治州",
            taxon_name="灰杨",
            scientific_name="Populus pruinosa",
        )

        response = self.client.get(
            "/api/germplasm/accessions/",
            {
                "q": "GA1",
                "taxon": "胡杨",
                "site": "柯坪",
                "isCore": "true",
                "current": "1",
                "pageSize": "5",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["current"], 1)
        self.assertEqual(payload["pageSize"], 5)
        item = payload["items"][0]
        self.assertEqual(item["id"], accession.id)
        self.assertEqual(item["accessionCode"], "GA1")
        self.assertEqual(item["sampleCode"], "GA1")
        self.assertEqual(item["taxon"]["nameCn"], "胡杨")
        self.assertEqual(item["sourceSite"]["name"], "阿克苏地区柯坪县")
        self.assertEqual(item["materialType"], "DNA")
        self.assertEqual(item["resourceType"], "胡杨古树特异资源")
        self.assertEqual(item["sex"], "雌株")
        self.assertTrue(item["isCore"])
        self.assertEqual(item["storageStatus"], "在库")
        self.assertEqual(item["sourceResourceId"], accession.source_resource_id)

    def test_accession_list_rejects_invalid_query_params(self):
        response = self.client.get(
            "/api/germplasm/accessions/",
            {"current": "0", "pageSize": "10"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("detail", response.json())

        response = self.client.get(
            "/api/germplasm/accessions/",
            {"isCore": "not-bool"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("detail", response.json())

    def test_accession_list_respects_source_resource_visibility(self):
        self.create_accession(
            accession_code="VISIBLE1",
            sample_code="VISIBLE1",
            resource_code="visible-resource",
            maintainer=self.user,
        )
        other_user = get_user_model().objects.create_user(
            username="other-owner", password="pass12345"
        )
        self.create_accession(
            accession_code="HIDDEN1",
            sample_code="HIDDEN1",
            resource_code="hidden-resource",
            maintainer=other_user,
        )
        GermplasmAccession.objects.create(
            accession_code="NORESOURCE",
            sample_code="NORESOURCE",
            material_type="DNA",
            storage_status="待整理",
        )

        response = self.client.get("/api/germplasm/accessions/", {"pageSize": "20"})

        self.assertEqual(response.status_code, 200)
        codes = {item["accessionCode"] for item in response.json()["items"]}
        self.assertEqual(codes, {"VISIBLE1", "HIDDEN1", "NORESOURCE"})

    def create_accession(
        self,
        *,
        accession_code: str,
        sample_code: str,
        is_core: bool = False,
        resource_type: str = "胡杨群体种质资源",
        site_name: str = "阿克苏地区",
        taxon_name: str = "胡杨",
        scientific_name: str = "Populus euphratica",
        resource_code: str | None = None,
        maintainer=None,
    ) -> GermplasmAccession:
        taxon = Taxon.objects.create(
            code=f"{accession_code.lower()}-taxon",
            name_cn=taxon_name,
            scientific_name=scientific_name,
        )
        site = Site.objects.create(
            site_code=f"{accession_code.lower()}-site",
            name=site_name,
            longitude=79.521,
            latitude=40.217,
            altitude=1059,
        )
        resource = DataResource.objects.create(
            name=f"{accession_code} DNA样品清单",
            code=resource_code or f"{accession_code.lower()}-resource",
            data_type=DataResource.DataType.TABLE,
            status=DataResource.Status.ACTIVE,
            maintainer=maintainer if maintainer is not None else self.user,
        )
        return GermplasmAccession.objects.create(
            accession_code=accession_code,
            sample_code=sample_code,
            taxon=taxon,
            source_site=site,
            material_type="DNA",
            resource_type=resource_type,
            sex="雌株",
            is_core=is_core,
            storage_status="在库",
            source_resource=resource,
        )


def grant(user, *specs):
    for app_label, codename in specs:
        permission = Permission.objects.get(
            content_type__app_label=app_label, codename=codename
        )
        user.user_permissions.add(permission)
