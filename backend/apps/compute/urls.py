from django.urls import path
from . import views

urlpatterns = [
    path("runtime/", views.runtime),
    path("categories/", views.categories),
    path("algorithms/", views.algorithms),
    path("algorithms/<int:algorithm_id>/", views.algorithm_detail),
    path("algorithms/<int:algorithm_id>/versions/", views.versions),
    path("versions/<int:version_id>/", views.version_action),
    path("versions/<int:version_id>/package/", views.package_file),
    path("templates/<int:template_id>/", views.template_file),
    path("inputs/", views.inputs),
    path("preflight/", views.preflight),
    path("tasks/", views.tasks),
    path("tasks/<uuid:task_id>/", views.task_detail),
    path("outputs/<int:output_id>/file/", views.output_file),
    path("outputs/<int:output_id>/preview/", views.output_preview),
    path("outputs/<int:output_id>/map-preview/", views.output_map_preview),
    path("outputs/<int:output_id>/map-preview/image/", views.output_map_image),
    path("outputs/<int:output_id>/import/", views.output_import),
]
