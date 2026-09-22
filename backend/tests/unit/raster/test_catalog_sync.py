from django.test import TestCase

from apps.catalog.models import DataResource, MapLayer
from apps.core.initialization import SUPERADMIN_GROUP_NAME
from apps.raster.models import RasterDataset
from apps.raster.services.catalog_sync import upsert_catalog_records


class RasterCatalogSyncTests(TestCase):
    def test_scanned_raster_resource_has_unknown_uploader_and_superadmin_access(self):
        dataset = RasterDataset.objects.create(
            name="扫描栅格",
            code="scan-raster",
            source_relative_path="source.tif",
            processed_relative_path="processed/source.cog.tif",
            source_file_size=10,
            processed_file_size=20,
            status=RasterDataset.Status.READY,
        )

        resource, layer = upsert_catalog_records(
            dataset=dataset,
            source_info={},
            processed_info={"stac": {"proj:epsg": 3857}},
            default_rules={"mode": "gray", "bands": [1]},
            bounds_4326=[87.0, 43.0, 88.0, 44.0],
        )

        self.assertIsNone(resource.maintainer)
        self.assertEqual(
            set(resource.access_groups.values_list("name", flat=True)),
            {SUPERADMIN_GROUP_NAME},
        )
        self.assertEqual(
            set(layer.access_groups.values_list("name", flat=True)),
            {SUPERADMIN_GROUP_NAME},
        )
        self.assertEqual(resource.data_type, DataResource.DataType.RASTER)
        self.assertEqual(layer.layer_type, MapLayer.LayerType.RASTER)
        self.assertNotIn(dataset.source_relative_path, resource.description)
        self.assertNotIn(dataset.processed_relative_path, resource.description)

    def test_raster_import_persists_authoritative_category(self):
        dataset = RasterDataset.objects.create(
            name="胡杨景观遥感",
            code="landscape-raster",
            source_relative_path="landscape.tif",
            processed_relative_path="processed/landscape.cog.tif",
            status=RasterDataset.Status.READY,
        )

        resource, _layer = upsert_catalog_records(
            dataset=dataset,
            source_info={},
            processed_info={"stac": {"proj:epsg": 3857}},
            default_rules={"mode": "gray", "bands": [1]},
            bounds_4326=[79.0, 39.0, 82.0, 42.0],
            category_code="spatial",
        )

        self.assertEqual(resource.category.code, "spatial")

    def test_categorical_raster_uses_full_default_opacity(self):
        dataset = RasterDataset.objects.create(
            name="LUCC 分类",
            code="lucc-raster",
            source_relative_path="lucc.tif",
            processed_relative_path="processed/lucc.cog.tif",
            raster_kind=RasterDataset.RasterKind.CATEGORICAL,
            status=RasterDataset.Status.READY,
        )

        _resource, layer = upsert_catalog_records(
            dataset=dataset,
            source_info={},
            processed_info={"stac": {"proj:epsg": 3857}},
            default_rules={"mode": "unique", "bands": [1]},
            bounds_4326=[106.7, 37.0, 107.0, 37.2],
            category_code="spatial",
        )

        self.assertEqual(layer.default_opacity, 100)
