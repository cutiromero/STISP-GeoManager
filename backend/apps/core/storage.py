from __future__ import annotations

from pathlib import Path

from django.conf import settings


class StoragePathError(ValueError):
    pass


def app_path(*parts: str) -> Path:
    return _safe_join(settings.PROJECT_CONFIG.app_data, *parts)


def research_path(*parts: str) -> Path:
    from apps.projects.context import selected_project_id

    project_id = selected_project_id()
    prefix = ("projects", str(project_id)) if project_id != 1 else ()
    return _safe_join(settings.PROJECT_CONFIG.research_data_root, *prefix, *parts)


def vector_geopackage_path() -> Path:
    return research_path("vector", "vector.gpkg")


def vector_original_path(relative_path: str = "") -> Path:
    return (
        research_path("vector", "original", relative_path)
        if relative_path
        else research_path("vector", "original")
    )


def validate_vector_layer_name(layer_name: str) -> str:
    layer_name = layer_name.strip()
    if not layer_name:
        raise StoragePathError("矢量图层未配置 GeoPackage 图层名")
    path_part = Path(layer_name)
    if path_part.is_absolute() or len(path_part.parts) != 1 or ".." in path_part.parts:
        raise StoragePathError(f"非法 GeoPackage 图层名：{layer_name}")
    if layer_name.endswith(".gpkg"):
        raise StoragePathError(
            "矢量数据字段应填写 GeoPackage 内的图层名，不是 .gpkg 文件路径"
        )
    return layer_name


def raster_source_path(relative_path: str) -> Path:
    return research_path("raster", "original", relative_path)


def raster_processed_path(relative_path: str) -> Path:
    return research_path("raster", "preprocessed", relative_path)


def raster_metadata_path(relative_path: str) -> Path:
    return research_path("raster", "metadata", relative_path)


def raster_tile_pyramid_path(
    dataset_id: int, style_hash: str, renderer_version: int
) -> Path:
    """Return the private, content-addressed MBTiles cache path for one style."""

    return app_path(
        "cache",
        "raster-tiles",
        f"v{int(renderer_version)}",
        str(int(dataset_id)),
        f"{style_hash}.mbtiles",
    )


def gene_data_path(relative_path: str = "") -> Path:
    return (
        research_path("gene", relative_path) if relative_path else research_path("gene")
    )


def table_data_path(relative_path: str = "") -> Path:
    return (
        research_path("table", relative_path)
        if relative_path
        else research_path("table")
    )


def _safe_join(root: Path, *parts: str) -> Path:
    root = root.resolve()
    candidate = root
    for part in parts:
        path_part = Path(part)
        if path_part.is_absolute() or ".." in path_part.parts:
            raise StoragePathError(f"非法路径片段：{part}")
        candidate = candidate / path_part
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise StoragePathError("路径越过了配置的数据根目录") from exc
    return candidate
