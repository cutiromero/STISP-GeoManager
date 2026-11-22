from django.urls import path, re_path
from . import hermes_views, views, workflow_report_views, workflow_validation_views
from .run_stream import response as run_stream
from .capability_views import capabilities
from .tool_call_views import tool_calls
from .operation_views import operations, operation_detail

urlpatterns = [
    path("hermes/v1/capabilities", hermes_views.capabilities),
    re_path(r"^hermes/v1/(?P<kind>skills|toolsets)$", hermes_views.discovery),
    path("hermes/api/sessions", hermes_views.sessions),
    path("hermes/api/sessions/<str:session_id>", hermes_views.session_detail),
    path("hermes/api/sessions/<str:session_id>/messages", hermes_views.messages),
    path("hermes/v1/runs", hermes_views.runs),
    re_path(r"^hermes/v1/runs/(?P<run_id>run_[0-9a-f]{32})$", hermes_views.run_status),
    re_path(
        r"^hermes/v1/runs/(?P<run_id>run_[0-9a-f]{32})/events$", hermes_views.events
    ),
    re_path(
        r"^hermes/v1/runs/(?P<run_id>run_[0-9a-f]{32})/(?P<action>stop|clarify|approval)$",
        hermes_views.run_control,
    ),
    path("capabilities/", capabilities),
    path("runs/<int:run_id>/operations/", operations),
    path("operations/<uuid:operation_id>/", operation_detail),
    path("runs/<int:run_id>/tool-calls/", tool_calls),
    path("bootstrap/", views.bootstrap),
    path("attachments/", views.upload_attachment),
    path("conversations/", views.conversations),
    path("conversations/<int:conversation_id>/", views.conversation_detail),
    path(
        "conversations/<int:conversation_id>/deletion-preview/",
        views.conversation_deletion_preview,
    ),
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
    path("runs/<int:run_id>/stream/", run_stream),
    path("runs/<int:run_id>/cancel/", views.cancel),
    path("runs/<int:run_id>/interaction/", views.interaction),
    path("runs/<int:run_id>/compute-tasks/", views.compute_tasks),
    path("runs/<int:run_id>/compute-intent/", views.compute_intent),
    path("runs/<int:run_id>/research-intent/", views.research_intent),
    path("research-demos/", views.research_demos),
    path("resources/", views.resource_list),
    path("workflow-uploads/", views.workflow_uploads),
    path("workflow-uploads/batch/", views.workflow_upload_batch),
    path("workflow-uploads/references/", views.workflow_catalog_references),
    path("logic-configuration/", views.logic_configuration),
    path("workflow-uploads/recognize/", views.workflow_recognize_roles),
    path("workflow-uploads/<uuid:upload_id>/", views.workflow_upload_detail),
    path("workflows/", views.workflow_submit),
    path("workflows/active/", views.workflow_active),
    path("workflows/<uuid:workflow_id>/", views.workflow_detail),
    path("workflows/<uuid:workflow_id>/cancel/", views.workflow_cancel),
    path("workflows/<uuid:workflow_id>/confirm/", views.workflow_confirm),
    path(
        "workflows/<uuid:workflow_id>/retained-review/", views.workflow_retained_review
    ),
    path("workflows/<uuid:workflow_id>/retry-imports/", views.workflow_retry_imports),
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
    path(
        "workflows/<uuid:workflow_id>/validation/",
        workflow_validation_views.workflow_validation,
    ),
    path(
        "workflows/<uuid:workflow_id>/validation/files/<str:file_key>/preview/",
        workflow_validation_views.workflow_validation_preview,
    ),
    path(
        "workflows/<uuid:workflow_id>/validation/files/<str:file_key>/download/",
        workflow_validation_views.workflow_validation_download,
    ),
    path("admin/", views.admin),
]
