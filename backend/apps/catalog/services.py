from __future__ import annotations

import hashlib
import logging

from django.db import OperationalError, ProgrammingError

from apps.catalog.models import DataResource, MapLayer
from apps.catalog.vector_store import (
    geopackage_layer_metadata,
    geopackage_layer_names,
)
from apps.core.initialization import ensure_superadmin_defaults
from apps.core.storage import gene_data_path, table_data_path, vector_geopackage_path
from apps.standards.models import DataDomainType


logger = logging.getLogger(__name__)
GENE_FILE_EXTENSIONS = {
    ".fa",
    ".fasta",
    ".fq",
    ".fastq",
    ".vcf",
    ".gff",
    ".gff3",
    ".gb",
    ".gbk",
}
TABLE_FILE_EXTENSIONS = {".csv", ".tsv", ".xls", ".xlsx"}


def stable_catalog_code(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def scan_nongeographic_files() -> list[DataResource]:
    resources: list[DataResource] = []
    resources.extend(
        _scan_nongeographic_kind(
            DataResource.DataType.GENE, gene_data_path(), GENE_FILE_EXTENSIONS
        )
    )
    resources.extend(
        _scan_nongeographic_kind(
            DataResource.DataType.TABLE, table_data_path(), TABLE_FILE_EXTENSIONS
        )
    )
    return resources


def scan_vector_geopackage_layers() -> list[DataResource]:
    path = vector_geopackage_path()
    if not path.exists():
        return []
    try:
        layer_names = geopackage_layer_names(path)
    except Exception:
        logger.exception("读取统一 GeoPackage 图层列表失败：%s", path)
        return []

    resources: list[DataResource] = []
    for layer_name in layer_names:
        try:
            resources.append(upsert_vector_catalog_record(path, layer_name))
        except Exception:
            logger.exception("扫描登记 GeoPackage 图层失败：%s", layer_name)
    return resources


def scan_catalog_sources() -> list[DataResource]:
    from apps.projects.context import ProjectScope, current_scope, project_scope

    # Startup discovery scans only the default project's research directories.
    if current_scope.get() is None:
        with project_scope(ProjectScope((1,), 1)):
            return scan_catalog_sources()
    resources: list[DataResource] = []
    resources.extend(scan_vector_geopackage_layers())
    resources.extend(scan_nongeographic_files())
    return resources


def scan_catalog_sources_safely() -> list[DataResource]:
    try:
        return scan_catalog_sources()
    except (OperationalError, ProgrammingError):
        logger.debug("数据目录扫描跳过：数据库尚未就绪")
    except Exception:
        logger.exception("数据目录扫描失败")
    return []


def upsert_vector_catalog_record(path, layer_name: str) -> DataResource:
    metadata = geopackage_layer_metadata(path, layer_name)
    bounds = metadata.bounds
    spatial_extent = ",".join(f"{value:.6f}" for value in bounds) if bounds else ""
    code = stable_catalog_code("vector", layer_name)
    resource = DataResource.objects.filter(code=code).first()
    preserves_user_metadata = bool(
        resource is not None and resource.maintainer_id is not None
    )
    _, superadmin_group = ensure_superadmin_defaults(
        create_account=False, attach_existing_superusers=False
    )

    if resource is None:
        resource = DataResource(code=code)

    if preserves_user_metadata:
        resource.data_type = DataResource.DataType.VECTOR
        resource.spatial_extent = spatial_extent
        resource.coordinate_system = metadata.coordinate_system
        resource.file_format = "GPKG"
        resource.storage_path = layer_name
        resource.item_count = metadata.feature_count
        resource.status = DataResource.Status.ACTIVE
    else:
        resource.name = layer_name
        resource.data_type = DataResource.DataType.VECTOR
        resource.source = "矢量数据目录扫描"
        resource.provider = ""
        resource.spatial_extent = spatial_extent
        resource.coordinate_system = metadata.coordinate_system
        resource.file_format = "GPKG"
        resource.storage_path = layer_name
        resource.description = f"自动扫描统一 GeoPackage 图层：{layer_name}"
        resource.quality_note = ""
        resource.size_bytes = path.stat().st_size
        resource.item_count = metadata.feature_count
        resource.maintainer = None
        resource.status = DataResource.Status.ACTIVE
    resource.save()

    map_layer = MapLayer.objects.filter(code=code).first()
    layer_created = map_layer is None
    if map_layer is None:
        map_layer = MapLayer(code=code)
    if layer_created or not preserves_user_metadata:
        map_layer.name = resource.name if preserves_user_metadata else layer_name
        map_layer.default_visible = False
        map_layer.default_opacity = 85
        map_layer.legend = ""
    map_layer.layer_type = MapLayer.LayerType.VECTOR
    map_layer.geometry_type = _map_geometry_type(metadata.geometry_type)
    map_layer.data_resource = resource
    map_layer.source_path = layer_name
    map_layer.bounds = bounds
    map_layer.is_active = True
    map_layer.save()

    if preserves_user_metadata:
        map_layer.access_groups.set(resource.access_groups.all())
    else:
        resource.access_groups.set([superadmin_group])
        map_layer.access_groups.set([superadmin_group])
    return resource


def _map_geometry_type(value: str) -> str:
    normalized = value.lower()
    if "point" in normalized:
        return MapLayer.GeometryType.POINT
    if "line" in normalized:
        return MapLayer.GeometryType.LINE
    if "polygon" in normalized:
        return MapLayer.GeometryType.POLYGON
    return MapLayer.GeometryType.MIXED


def upsert_nongeographic_catalog_record(
    data_type: DataResource.DataType, path
) -> DataResource:
    relative_path = path.relative_to(gene_data_path().parent).as_posix()
    code = stable_catalog_code(data_type.value, relative_path)
    data_type_label = (
        "基因数据" if data_type == DataResource.DataType.GENE else "表格数据"
    )
    resource, _ = DataResource.objects.update_or_create(
        code=code,
        defaults={
            "name": path.stem,
            "data_type": data_type,
            "domain_type": (
                DataDomainType.GENOME if data_type == DataResource.DataType.GENE else ""
            ),
            "source": "非地理数据目录扫描",
            "provider": "",
            "spatial_extent": "",
            "coordinate_system": "",
            "file_format": path.suffix.lstrip(".").upper(),
            "storage_path": relative_path,
            "description": f"自动扫描非地理{data_type_label}文件：{relative_path}",
            "quality_note": "",
            "size_bytes": path.stat().st_size,
            "item_count": 0,
            "maintainer": None,
            "status": DataResource.Status.ACTIVE,
        },
    )
    _, superadmin_group = ensure_superadmin_defaults(
        create_account=False, attach_existing_superusers=False
    )
    resource.access_groups.set([superadmin_group])
    return resource


def _scan_nongeographic_kind(
    data_type: DataResource.DataType, root, extensions: set[str]
) -> list[DataResource]:
    if not root.exists():
        return []
    resources: list[DataResource] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.suffix.lower() not in extensions:
            continue
        resources.append(upsert_nongeographic_catalog_record(data_type, path))
    return resources
