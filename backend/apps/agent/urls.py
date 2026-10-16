from django.urls import path
from . import views, workflow_report_views

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
    path("runs/<int:run_id>/interaction/", views.interaction),
    path("runs/<int:run_id>/compute-tasks/", views.compute_tasks),
    path("runs/<int:run_id>/compute-intent/", views.compute_intent),
    path("runs/<int:run_id>/research-intent/", views.research_intent),
    path("research-demos/", views.research_demos),
    path("resources/", views.resource_list),
    path("workflows/", views.workflow_submit),
    path("workflows/<uuid:workflow_id>/", views.workflow_detail),
    path("workflows/<uuid:workflow_id>/cancel/", views.workflow_cancel),
    path("workflows/<uuid:workflow_id>/confirm/", views.workflow_confirm),
    path("workflows/<uuid:workflow_id>/pause/", views.workflow_pause),
    path("workflows/<uuid:workflow_id>/resume/", views.workflow_resume),
    path("workflows/<uuid:workflow_id>/report/", workflow_report_views.workflow_report),
    path(
        "workflows/<uuid:workflow_id>/report/preview/",
        workflow_report_views.workflow_report_preview,
    ),
    path(
        "workflows/<uuid:workflow_id>/report/download/",
        workflow_report_views.workflow_report_download,
    ),
    path(
        "workflows/<uuid:workflow_id>/report/import/",
        workflow_report_views.workflow_report_import,
    ),
    path("admin/", views.admin),
]
