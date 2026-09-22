from django.urls import path
from . import views

urlpatterns = [
    path("projects/", views.projects),
    path("projects/<int:project_id>/", views.project_detail),
    path("projects/assignments/<int:user_id>/", views.assignments),
]
