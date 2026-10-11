from django.urls import path
from . import views

urlpatterns = [
    path("bootstrap/", views.bootstrap),
    path("attachments/", views.upload_attachment),
    path("conversations/", views.conversations),
    path("conversations/<int:conversation_id>/", views.conversation_detail),
    path(
        "conversations/<int:conversation_id>/attachments/",
        views.conversation_attachments,
    ),
    path(
        "conversations/<int:conversation_id>/attachments/<int:attachment_id>/",
        views.attachment_detail,
    ),
    path("conversations/<int:conversation_id>/runs/", views.submit),
    path("runs/<int:run_id>/", views.run_detail),
    path("runs/<int:run_id>/cancel/", views.cancel),
    path("runs/<int:run_id>/compute-tasks/", views.compute_tasks),
    path("runs/<int:run_id>/compute-intent/", views.compute_intent),
    path("runs/<int:run_id>/research-intent/", views.research_intent),
    path("research-demos/", views.research_demos),
    path("resources/", views.resource_list),
    path("workflows/", views.workflow_submit),
    path("workflows/<uuid:workflow_id>/", views.workflow_detail),
    path("workflows/<uuid:workflow_id>/cancel/", views.workflow_cancel),
    path("workflows/<uuid:workflow_id>/confirm/", views.workflow_confirm),
    path("admin/", views.admin),
]
