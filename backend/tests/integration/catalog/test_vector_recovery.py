import json
import tempfile
from dataclasses import replace
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings

from apps.catalog.models import DataResource, VectorDataset
from apps.catalog.vector_store import (
    DataQueryError,
    geopackage_layer_exists,
    read_resource,
)
from apps.core.storage import vector_geopackage_path, vector_original_path


class VectorLayerRecoveryTests(TestCase):
    def test_missing_layer_is_rebuilt_from_archived_geojson(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            config = replace(
                settings.PROJECT_CONFIG,
                app_data=Path(tmpdir) / "app",
                research_data_root=Path(tmpdir) / "research",
            )
            with override_settings(PROJECT_CONFIG=config):
                archive_path = vector_original_path("uploaded/source.geojson")
                archive_path.parent.mkdir(parents=True, exist_ok=True)
                archive_path.write_text(
                    json.dumps(
                        {
                            "type": "FeatureCollection",
                            "features": [
                                {
                                    "type": "Feature",
                                    "properties": {"name": "sample"},
                                    "geometry": {
                                        "type": "Point",
                                        "coordinates": [87.6, 43.8],
                                    },
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                resource = DataResource.objects.create(
                    name="恢复测试",
                    code="vector-recovery-test",
                    data_type=DataResource.DataType.VECTOR,
                    storage_path="recovered_layer",
                    status=DataResource.Status.ACTIVE,
                )
                VectorDataset.objects.create(
                    resource=resource,
                    source_file_name="source.geojson",
                    source_format=VectorDataset.SourceFormat.GEOJSON,
                    source_archive_path="uploaded/source.geojson",
                    source_layer_name="source",
                    source_crs="EPSG:4326",
                    normalized_epsg=4326,
                    geometry_type="Point",
                    feature_count=1,
                    import_summary={"stableFeatureIdField": "_gm_id"},
                )

                frame = read_resource(resource)

                self.assertEqual(len(frame), 1)
                self.assertEqual(frame.iloc[0]["name"], "sample")
                self.assertTrue(
                    geopackage_layer_exists(
                        vector_geopackage_path(), resource.storage_path
                    )
                )

    def test_missing_layer_without_archive_returns_actionable_error(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            config = replace(
                settings.PROJECT_CONFIG,
                app_data=Path(tmpdir) / "app",
                research_data_root=Path(tmpdir) / "research",
            )
            with override_settings(PROJECT_CONFIG=config):
                resource = DataResource.objects.create(
                    name="无归档测试",
                    code="vector-no-archive-test",
                    data_type=DataResource.DataType.VECTOR,
                    storage_path="missing_layer",
                    status=DataResource.Status.ACTIVE,
                )

                with self.assertRaisesMessage(
                    DataQueryError,
                    "原始矢量图层已缺失且没有可用归档，请重新导入该数据后再加载工程",
                ):
                    read_resource(resource)
