from __future__ import annotations

import logging

from django.core.files import File

from apps.catalog.models import DataResource, VectorDataset
from apps.catalog.vector_storage import (
    GEOPACKAGE_WRITE_LOCK,
    append_geopackage_layer,
)
from apps.core.storage import vector_original_path


logger = logging.getLogger(__name__)


def recover_vector_layer_from_archive(resource: DataResource) -> bool:
    dataset = VectorDataset.objects.filter(resource=resource).first()
    if dataset is None or not dataset.source_archive_path:
        return False
    archive_path = vector_original_path(dataset.source_archive_path)
    if not archive_path.exists() or not archive_path.is_file():
        return False

    from apps.catalog.vector_importer import (
        discover_vector_layers,
        prepare_vector_frame,
        read_vector_layer,
        staged_vector_upload,
    )
    from apps.catalog.vector_store import geopackage_layer_exists
    from apps.core.storage import vector_geopackage_path

    target_path = vector_geopackage_path()
    target_layer = resource.storage_path
    try:
        with archive_path.open("rb") as stream:
            uploaded = File(stream, name=dataset.source_file_name or archive_path.name)
            with staged_vector_upload(uploaded) as staged:
                sources = discover_vector_layers(
                    staged, encoding=dataset.source_encoding or None
                )
                source = next(
                    (
                        candidate
                        for candidate in sources
                        if candidate.source_layer_name == dataset.source_layer_name
                    ),
                    sources[0] if len(sources) == 1 else None,
                )
                if source is None:
                    return False
                frame, _resolved_encoding = read_vector_layer(source)
                source_crs = dataset.source_crs or (
                    f"EPSG:{dataset.source_epsg}" if dataset.source_epsg else None
                )
                frame, _issues = prepare_vector_frame(
                    frame,
                    source_crs=source_crs,
                    repair_invalid=True,
                    skip_invalid=True,
                    normalize_crs=True,
                )
                stable_id_field = str(
                    dataset.import_summary.get("stableFeatureIdField") or "_gm_id"
                )
                if stable_id_field not in frame.columns:
                    frame.insert(0, stable_id_field, range(1, len(frame) + 1))

        with GEOPACKAGE_WRITE_LOCK:
            if geopackage_layer_exists(target_path, target_layer):
                return True
            append_geopackage_layer(target_path, target_layer, frame)
        logger.warning(
            "已从原始归档自动恢复 GeoPackage 图层：resource=%s layer=%s",
            resource.id,
            target_layer,
        )
        return True
    except Exception:
        logger.exception(
            "从原始归档恢复 GeoPackage 图层失败：resource=%s layer=%s",
            resource.id,
            target_layer,
        )
        return False
