from django.urls import path

from apps.catalog import map_compositions, nongeo, results, views


urlpatterns = [
    path("catalog/directories/", views.directories, name="catalog-directories"),
    path("catalog/resources/", views.resources, name="catalog-resources"),
    path("catalog/results/", results.result_artifacts, name="catalog-results"),
    path(
        "catalog/results/<int:result_id>/",
        results.result_artifact_detail,
        name="catalog-result-detail",
    ),
    path(
        "catalog/results/<int:result_id>/file/",
        results.result_artifact_file,
        name="catalog-result-file",
    ),
    path("catalog/workspaces/", views.workspaces, name="catalog-workspaces"),
    path(
        "catalog/workspaces/<int:workspace_id>/",
        views.workspace_detail,
        name="catalog-workspace-detail",
    ),
    path(
        "catalog/map-compositions/",
        map_compositions.map_compositions,
        name="catalog-map-compositions",
    ),
    path(
        "catalog/map-compositions/<int:composition_id>/",
        map_compositions.map_composition_detail,
        name="catalog-map-composition-detail",
    ),
    path(
        "catalog/map-compositions/<int:composition_id>/versions/",
        map_compositions.create_map_composition_version,
        name="catalog-map-composition-versions",
    ),
    path(
        "catalog/map-compositions/<int:composition_id>/versions/<int:version_number>/file/",
        map_compositions.map_composition_version_file,
        name="catalog-map-composition-version-file",
    ),
    path(
        "catalog/map-compositions/<int:composition_id>/publish/",
        map_compositions.publish_map_composition,
        name="catalog-map-composition-publish",
    ),
    path(
        "catalog/map-compositions/<int:composition_id>/unpublish/",
        map_compositions.unpublish_map_composition,
        name="catalog-map-composition-unpublish",
    ),
    path(
        "catalog/map-compositions/<int:composition_id>/restore-project/",
        map_compositions.restore_map_composition_project,
        name="catalog-map-composition-restore-project",
    ),
    path("admin/workspaces/", views.admin_workspaces, name="admin-workspaces"),
    path(
        "admin/workspaces/<int:workspace_id>/",
        views.admin_workspace_detail,
        name="admin-workspace-detail",
    ),
    path("catalog/scan/", views.scan_sources, name="catalog-scan"),
    path(
        "catalog/import/preview/", views.import_preview, name="catalog-import-preview"
    ),
    path(
        "catalog/import/validate/",
        views.import_validate,
        name="catalog-import-validate",
    ),
    path("catalog/import/commit/", views.import_commit, name="catalog-import-commit"),
    path(
        "catalog/vector-import/preview/",
        views.vector_import_preview,
        name="catalog-vector-import-preview",
    ),
    path(
        "catalog/vector-import/validate/",
        views.vector_import_validate,
        name="catalog-vector-import-validate",
    ),
    path(
        "catalog/vector-import/commit/",
        views.vector_import_commit,
        name="catalog-vector-import-commit",
    ),
    path(
        "catalog/resources/<int:pk>/profile/",
        views.resource_profile,
        name="catalog-resource-profile",
    ),
    path(
        "catalog/resources/<int:pk>/visualization-summary/",
        views.resource_visualization_summary_view,
        name="catalog-resource-visualization-summary",
    ),
    path(
        "catalog/resources/<int:pk>/nongeo-analysis/",
        nongeo.resource_nongeo_analysis,
        name="catalog-resource-nongeo-analysis",
    ),
    path(
        "catalog/resources/<int:pk>/nongeo-query/",
        nongeo.resource_nongeo_query,
        name="catalog-resource-nongeo-query",
    ),
    path(
        "catalog/resources/<int:pk>/query/",
        views.resource_query,
        name="catalog-resource-query",
    ),
    path("catalog/export/", views.export_loaded_layers, name="catalog-export"),
    path(
        "catalog/export/async/",
        views.export_loaded_layers_async,
        name="catalog-export-async",
    ),
    path(
        "catalog/export/jobs/<str:job_id>/download/",
        views.export_job_download,
        name="catalog-export-download",
    ),
    path("layers/", views.layers, name="layers"),
    path("search/", views.search, name="search"),
]
