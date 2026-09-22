from django.urls import path

from apps.raster import views


urlpatterns = [
    path("datasets/", views.datasets, name="raster-datasets"),
    path("import/preview/", views.preview_import, name="raster-import-preview"),
    path("import/", views.import_raster, name="raster-import"),
    path("scan/", views.scan_sources, name="raster-scan"),
    path("render/", views.render, name="raster-render"),
    path("render/async/", views.render_async, name="raster-render-async"),
    path("unique-values/", views.unique_values, name="raster-unique-values"),
    path("jobs/<str:job_id>/", views.job_status, name="raster-job-status"),
    path(
        "tiles/<int:dataset_id>/<str:style_hash>/<int:z>/<int:x>/<int:y>.png",
        views.tile,
        name="raster-tile",
    ),
]
