from django.urls import path
from . import library_views, views

urlpatterns = [
    path("entries/", views.entries, name="knowledge_entries"),
    path("entries/<int:entry_id>/", views.detail, name="knowledge_detail"),
    path("check/", views.check, name="knowledge_check"),
    path("documents/", library_views.documents, name="knowledge_documents"),
    path("documents/search/", library_views.search, name="knowledge_documents_search"),
    path(
        "documents/<int:document_id>/",
        library_views.classify,
        name="knowledge_document_classify",
    ),
    path(
        "documents/<int:document_id>/retry/",
        library_views.retry,
        name="knowledge_document_retry",
    ),
    path("wiki/", library_views.wiki, name="knowledge_wiki"),
]
