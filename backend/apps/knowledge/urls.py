from django.urls import path
from . import views

urlpatterns = [
    path("entries/", views.entries, name="knowledge_entries"),
    path("entries/<int:entry_id>/", views.detail, name="knowledge_detail"),
    path("check/", views.check, name="knowledge_check"),
]
