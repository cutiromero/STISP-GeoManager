from apps.raster.services.catalog_sync import upsert_catalog_records
from apps.raster.services.color_mapping import (
    array_to_rgba,
    hex_to_rgba,
    palette_array,
    scale_array,
)
from apps.raster.services.constants import (
    DEFAULT_TILE_SIZE,
    PALETTES,
    RASTER_EXTENSIONS,
    UNIQUE_COLORS,
    WEB_MERCATOR_HALF_WORLD,
)
from apps.raster.services.exceptions import (
    RasterImportError,
    RasterJobError,
    RasterRenderError,
    RasterTileOutsideExtent,
)
from apps.raster.services.gdal_ops import gdalinfo_json, run_gdal_command
from apps.raster.services.geo_utils import (
    bounds_4326_from_gdalinfo,
    bounds_from_gdalinfo,
    image_coordinates_from_gdalinfo,
    intersects_bounds,
    style_hash_for,
    tile_bounds_3857,
    transparent_png,
)
from apps.raster.services.importer import (
    dataset_for_layer,
    handle_import_progress,
    import_raster_file,
    is_raster_file,
    metadata_relative_path,
    processed_relative_path,
    save_metadata,
    scan_unprocessed_source_files,
    scan_unprocessed_source_files_safely,
    stable_code,
    store_source_file,
    store_uploaded_source_file,
    validate_raster_pixel_size,
    validate_raster_upload_size,
)
from apps.raster.services.jobs import (
    RasterJob,
    get_job,
    get_job_artifact_path,
    open_job_artifact_for_download,
    start_export_job,
    start_import_job,
    start_render_job,
    start_scan_job,
)
from apps.raster.services.profile import dataset_for_resource, get_raster_profile
from apps.raster.services.renderer import (
    build_static_xyz_tile_pyramid,
    register_tile_style,
    render_xyz_tile,
)
from apps.raster.services.rules_engine import (
    band_min_max,
    band_data_type,
    default_raster_rules,
    is_integer_band,
    normalize_rules,
    normalize_alpha_band,
    normalize_nodata,
    normalize_stretch_bands,
    normalize_unique_values,
    output_source_bands,
    read_source_bands,
    stretch_min_max,
)
from apps.raster.services.serializers import (
    compact_raster_metadata,
    serialize_raster_dataset,
)
from apps.raster.services.unique_values import classify_unique_values

__all__ = [
    # exceptions
    "RasterRenderError",
    "RasterTileOutsideExtent",
    "RasterImportError",
    "RasterJobError",
    # constants
    "RASTER_EXTENSIONS",
    "WEB_MERCATOR_HALF_WORLD",
    "DEFAULT_TILE_SIZE",
    "PALETTES",
    "UNIQUE_COLORS",
    # jobs
    "RasterJob",
    "start_import_job",
    "start_scan_job",
    "start_render_job",
    "start_export_job",
    "get_job",
    "get_job_artifact_path",
    "open_job_artifact_for_download",
    # importer
    "scan_unprocessed_source_files",
    "scan_unprocessed_source_files_safely",
    "import_raster_file",
    "is_raster_file",
    "store_source_file",
    "store_uploaded_source_file",
    "validate_raster_pixel_size",
    "validate_raster_upload_size",
    "processed_relative_path",
    "metadata_relative_path",
    "stable_code",
    "gdalinfo_json",
    "save_metadata",
    "run_gdal_command",
    "handle_import_progress",
    "upsert_catalog_records",
    # renderer
    "build_static_xyz_tile_pyramid",
    "register_tile_style",
    "render_xyz_tile",
    # serializers
    "serialize_raster_dataset",
    "compact_raster_metadata",
    # importer (dataset lookup)
    "dataset_for_layer",
    "dataset_for_resource",
    "get_raster_profile",
    # rules engine
    "default_raster_rules",
    "normalize_rules",
    "normalize_stretch_bands",
    "normalize_unique_values",
    "band_min_max",
    "output_source_bands",
    "stretch_min_max",
    "read_source_bands",
    "normalize_alpha_band",
    "normalize_nodata",
    "band_data_type",
    "is_integer_band",
    "classify_unique_values",
    # color mapping
    "array_to_rgba",
    "scale_array",
    "palette_array",
    "hex_to_rgba",
    # geo utils
    "bounds_from_gdalinfo",
    "bounds_4326_from_gdalinfo",
    "image_coordinates_from_gdalinfo",
    "style_hash_for",
    "tile_bounds_3857",
    "intersects_bounds",
    "transparent_png",
]
