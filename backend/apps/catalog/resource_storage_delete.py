"""Delete only catalog-owned storage; preserve shared files and database containers."""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from uuid import uuid4

from django.db import DatabaseError, connection

from apps.catalog.models import DataResource, MapLayer, VectorDataset
from apps.catalog.vector_storage import GEOPACKAGE_WRITE_LOCK
from apps.core.storage import (
    StoragePathError,
    app_path,
    research_path,
    table_data_path,
    validate_vector_layer_name,
    vector_geopackage_path,
    vector_original_path,
)
from apps.raster.models import RasterDataset
from apps.projects.context import ProjectScope, project_scope

logger = logging.getLogger(__name__)


def _safe_file(root: Path, relative: str) -> Path:
    value = Path(relative)
    if value.is_absolute() or ".." in value.parts:
        raise StoragePathError("存储路径不属于当前项目的受控文件")
    candidate = root / value
    for parent in (candidate, *candidate.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise StoragePathError("符号链接文件需要管理员单独处理")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise StoragePathError("存储路径越过当前项目的数据目录")
    if resolved.exists() and not resolved.is_file():
        raise StoragePathError("资源路径不是可删除的独立文件")
    return resolved


def _project_path(project_id: int, callback, *parts) -> Path:
    with project_scope(ProjectScope((project_id,), project_id)):
        return callback(*parts)


def _resource_file(resource) -> Path | None:
    with project_scope(
        ProjectScope((resource.project_tag_id,), resource.project_tag_id)
    ):
        return _resource_file_in_project(resource)


def _resource_file_in_project(resource) -> Path | None:
    relative = resource.storage_path
    if not relative or resource.data_type in {"vector", "raster"}:
        return None
    if resource.data_type == "table" and resource.file_format.upper() == "SQLITE":
        return None
    # Registered document/image outputs may be relative to table/, while scans
    # store the table/ or gene/ prefix. Both resolve through the same project root.
    candidate = None
    if relative.startswith(("table/", "gene/")):
        candidate = _safe_file(research_path(), relative)
    elif resource.data_type in {"table", "document", "image"}:
        candidate = _safe_file(table_data_path(), relative)
    elif resource.data_type == "gene":
        candidate = _safe_file(research_path("gene"), relative)
    if candidate in {table_data_path("data.sqlite"), vector_geopackage_path()}:
        raise StoragePathError("统一数据库文件不能作为普通文件删除")
    return candidate


class ResourceStorageDeletion:
    """Stage files and SQLite changes before committing a metadata deletion."""

    def __init__(self, resource):
        self.resource = resource
        self.files: set[Path] = set()
        self.shared = False
        self.databases: list[tuple[Path, str, bool]] = []
        self.aliases: list[str] = []
        self.locked = False
        self.staged: list[tuple[Path, Path]] = []
        self.removed_count = 0
        self.cleanup_failed = False
        self.recovery_failed = False
        self._plan()

    def _plan(self):
        resource = self.resource
        # Inspect every project, comparing actual storage roots rather than
        # treating identical relative names in separate directories as shared.
        others = DataResource._base_manager.exclude(pk=resource.pk)
        linked_layers = resource.map_layers.values_list("id", flat=True)
        geographic = resource.data_type == "vector"
        database_path = (
            vector_geopackage_path() if geographic else table_data_path("data.sqlite")
        )
        path_callback = vector_geopackage_path if geographic else table_data_path
        path_parts = () if geographic else ("data.sqlite",)
        table_identity = resource.storage_path.strip().casefold()
        database_resources = others.filter(data_type=resource.data_type)
        if not geographic:
            database_resources = database_resources.filter(file_format__iexact="SQLITE")
        candidate_projects = {
            project_id
            for project_id, name in database_resources.values_list(
                "project_tag_id", "storage_path"
            )
            if name.strip().casefold() == table_identity
        }
        candidate_projects.update(
            project_id
            for project_id, name in MapLayer._base_manager.exclude(pk__in=linked_layers)
            .filter(layer_type=resource.data_type)
            .values_list("project_tag_id", "source_path")
            if name.strip().casefold() == table_identity
        )
        same_path = any(
            _project_path(project_id, path_callback, *path_parts) == database_path
            for project_id in candidate_projects
        )
        if resource.storage_path and resource.data_type == "vector":
            layer = validate_vector_layer_name(resource.storage_path)
            if layer.lower().startswith(("gpkg_", "sqlite_", "rtree_")):
                raise StoragePathError("系统内部表不能作为资源删除")
            if same_path:
                self.shared = True
            else:
                self.databases.append((vector_geopackage_path(), layer, True))
        elif (
            resource.storage_path
            and resource.data_type == "table"
            and (resource.file_format.upper() == "SQLITE")
        ):
            table = resource.storage_path
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", table) or (
                table.lower().startswith("sqlite_")
                or table.casefold() == "data_columns"
            ):
                raise StoragePathError("表格存储标识不合法")
            if same_path:
                self.shared = True
            else:
                self.databases.append((table_data_path("data.sqlite"), table, False))
        else:
            candidate = _resource_file(resource)
            if candidate:
                shared_files = set()
                for other in others:
                    try:
                        other_path = _resource_file(other)
                        if other_path:
                            shared_files.add(other_path)
                    except StoragePathError:
                        continue
                if candidate in shared_files:
                    self.shared = True
                else:
                    self.files.add(candidate)
        for dataset in VectorDataset.objects.filter(resource=resource):
            relative = dataset.source_archive_path
            if relative:
                candidate = _safe_file(vector_original_path(), relative)
                shared = False
                for other in VectorDataset._base_manager.exclude(pk=dataset.pk):
                    if not other.source_archive_path:
                        continue
                    try:
                        other_path = _safe_file(
                            _project_path(other.project_tag_id, vector_original_path),
                            other.source_archive_path,
                        )
                    except StoragePathError:
                        continue
                    if other_path == candidate:
                        shared = True
                        break
                if shared:
                    self.shared = True
                else:
                    self.files.add(candidate)
        self._plan_rasters()

    def _plan_rasters(self):
        datasets = list(self.resource.raster_datasets.all())
        own_ids = [dataset.id for dataset in datasets]
        others = RasterDataset._base_manager.exclude(pk__in=own_ids)
        fields = {
            "source_relative_path": "raster/original",
            "processed_relative_path": "raster/preprocessed",
            "source_metadata_relative_path": "raster/metadata",
            "processed_metadata_relative_path": "raster/metadata",
        }
        shared_files = set()
        for project_id, value in (
            DataResource._base_manager.filter(data_type="raster")
            .exclude(pk=self.resource.pk)
            .values_list("project_tag_id", "storage_path")
        ):
            if value:
                try:
                    shared_files.add(
                        _safe_file(
                            _project_path(
                                project_id, research_path, "raster/preprocessed"
                            ),
                            value,
                        )
                    )
                except StoragePathError:
                    continue
        for project_id, value in (
            MapLayer._base_manager.filter(layer_type="raster")
            .exclude(data_resource=self.resource)
            .values_list("project_tag_id", "source_path")
        ):
            if value:
                try:
                    shared_files.add(
                        _safe_file(
                            _project_path(
                                project_id, research_path, "raster/preprocessed"
                            ),
                            value,
                        )
                    )
                except StoragePathError:
                    continue
        for other in others:
            for field, root in fields.items():
                value = getattr(other, field)
                if value:
                    try:
                        shared_files.add(
                            _safe_file(
                                _project_path(
                                    other.project_tag_id, research_path, root
                                ),
                                value,
                            )
                        )
                    except StoragePathError:
                        continue
            try:
                self._raster_source_files(other, shared_files)
            except StoragePathError:
                continue
        if (
            not datasets
            and self.resource.data_type == "raster"
            and self.resource.storage_path
        ):
            candidate = _safe_file(
                research_path("raster/preprocessed"), self.resource.storage_path
            )
            if candidate in shared_files:
                self.shared = True
            else:
                self.files.add(candidate)
        for dataset in datasets:
            candidates = set()
            for field, root in fields.items():
                value = getattr(dataset, field)
                if value:
                    candidates.add(_safe_file(research_path(root), value))
            self._raster_source_files(dataset, candidates)
            for candidate in candidates:
                if candidate in shared_files:
                    self.shared = True
                else:
                    self.files.add(candidate)
            # Cache paths use globally unique dataset IDs; each leaf is a file.
            cache = app_path("cache", "raster-tiles")
            if cache.exists():
                for version in cache.iterdir():
                    if version.is_dir() and re.fullmatch(r"v\d+", version.name):
                        directory = version / str(dataset.id)
                        if directory.exists() and not directory.is_symlink():
                            for path in directory.iterdir():
                                if path.is_file():
                                    self.files.add(
                                        _safe_file(cache, str(path.relative_to(cache)))
                                    )

    @staticmethod
    def _raster_source_files(dataset, files: set[Path]):
        source = dataset.source_relative_path
        if not source:
            return
        parent = Path(source).parent
        for item in dataset.source_manifest or []:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            name = str(item["name"])
            if len(Path(name).parts) != 1:
                raise StoragePathError("栅格源文件清单包含非法文件名")
            files.add(
                _safe_file(
                    _project_path(
                        dataset.project_tag_id, research_path, "raster/original"
                    ),
                    str(parent / name),
                )
            )
        if source.startswith("uploaded/"):
            files.add(
                _safe_file(
                    _project_path(
                        dataset.project_tag_id, research_path, "raster/original"
                    ),
                    str(parent / "manifest.json"),
                )
            )

    def __enter__(self):
        # No storage mutations means no lock to retain until on_commit. This
        # also lets metadata-only TestCase requests finish without deferred locks.
        if not any(path.exists() for path in self.files) and not any(
            path.exists() for path, _, _ in self.databases
        ):
            return self
        GEOPACKAGE_WRITE_LOCK.acquire()
        self.locked = True
        try:
            for path, table, geographic in self.databases:
                if not path.exists():
                    continue
                if connection.vendor != "sqlite":
                    raise StoragePathError("当前数据库不支持资源存储事务删除")
                alias = "catalog_delete_" + uuid4().hex
                with connection.cursor() as cursor:
                    cursor.execute(f'ATTACH DATABASE %s AS "{alias}"', [str(path)])
                    self.aliases.append(alias)
                    self._drop_table(cursor, alias, table, geographic)
            for path in sorted(self.files):
                if path.exists():
                    staged = path.with_name(f".{path.name}.delete-{uuid4().hex}")
                    path.replace(staged)
                    self.staged.append((path, staged))
            return self
        except Exception:
            self.__exit__(*sys.exc_info())
            raise

    def _drop_table(self, cursor, alias: str, table: str, geographic: bool):
        def quote(name: str) -> str:
            return f'"{alias}"."' + name.replace('"', '""') + '"'

        tables = {
            row[0]
            for row in cursor.execute(
                f"SELECT name FROM \"{alias}\".sqlite_master WHERE type='table'"
            ).fetchall()
        }
        # SQLite resolves table names without case distinctions; metadata and
        # RTree cleanup must use the actual stored layer spelling as well.
        table = next(
            (name for name in tables if name.casefold() == table.casefold()), table
        )
        if geographic and "gpkg_geometry_columns" in tables:
            for row in cursor.execute(
                f"SELECT column_name FROM {quote('gpkg_geometry_columns')} WHERE table_name=%s",
                [table],
            ).fetchall():
                rtree = f"rtree_{table}_{row[0]}"
                if rtree in tables:
                    cursor.execute(f"DROP TABLE {quote(rtree)}")
        cursor.execute(f"DROP TABLE IF EXISTS {quote(table)}")
        for metadata in (
            (
                "gpkg_geometry_columns",
                "gpkg_data_columns",
                "gpkg_extensions",
                "gpkg_ogr_contents",
                "gpkg_contents",
            )
            if geographic
            else ("data_columns",)
        ):
            if metadata in tables:
                cursor.execute(
                    f"DELETE FROM {quote(metadata)} WHERE table_name=%s", [table]
                )
        self.removed_count += int(table in tables)

    def __exit__(self, exc_type, exc, traceback):
        # The owning Django transaction commits/rolls back every attached table.
        # Detach only after it ends, otherwise SQLite keeps the schema locked.
        if exc_type is not None:
            self.restore_staged_files()

    def restore_staged_files(self):
        """Restore original paths when the owning metadata transaction fails."""
        self.recovery_failed = False
        for path, staged in reversed(self.staged):
            if staged.exists():
                try:
                    staged.replace(path)
                except OSError:
                    self.recovery_failed = True
                    logger.exception(
                        "Catalog staged file restoration failed: %s", staged
                    )

    def finalize(self):
        """Metadata and storage transactions succeeded; remove isolated files."""
        for _, staged in self.staged:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                self.cleanup_failed = True
                logger.exception("Failed to remove staged catalog file %s", staged)
        self.close()

    def close(self):
        try:
            for alias in self.aliases:
                with connection.cursor() as cursor:
                    cursor.execute(f'DETACH DATABASE "{alias}"')
            self.aliases.clear()
        except DatabaseError:
            logger.exception("Catalog storage detach failed after transaction")
            if not connection.in_atomic_block:
                connection.close()
                self.aliases.clear()
        finally:
            if self.locked:
                GEOPACKAGE_WRITE_LOCK.release()
                self.locked = False

    @property
    def detail(self) -> str:
        text = "已删除资源登记及关联图层、数据集"
        if self.removed_count or self.staged:
            text += "，已清理独占的存储表与文件"
        if self.shared:
            text += "；其他资源共用的存储已保留"
        if self.cleanup_failed:
            text += "；部分隔离文件清理失败，请联系管理员"
        return text
