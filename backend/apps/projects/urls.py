from django.urls import path
from . import views

urlpatterns = [
    path("projects/", views.projects),
    path("projects/features/<slug:feature_key>/", views.global_feature),
    path(
        "projects/<int:project_id>/features/<slug:feature_key>/", views.project_feature
    ),
    path("projects/<int:project_id>/", views.project_detail),
    path("projects/<int:project_id>/deletion-preview/", views.project_deletion_preview),
    path("projects/assignments/<int:user_id>/", views.assignments),
]
