from django.urls import path
from . import views

urlpatterns = [
    path("", views.flows),
    path("runs/", views.runs),
    path("runs/<uuid:workflow_id>/", views.run_detail),
    path("runs/<uuid:workflow_id>/decide/", views.decide),
    path("runs/<uuid:workflow_id>/input-script/", views.input_script),
    path("runs/<uuid:workflow_id>/input-clarification/", views.input_clarification),
    path("runs/<uuid:workflow_id>/cancel/", views.control, {"action": "cancel"}),
    path("runs/<uuid:workflow_id>/pause/", views.control, {"action": "pause"}),
    path("runs/<uuid:workflow_id>/resume/", views.control, {"action": "resume"}),
    path("<int:flow_id>/", views.flow_detail),
    path("<int:flow_id>/versions/", views.versions),
    path("<int:flow_id>/start/", views.start),
    path("<int:flow_id>/prepare-inputs/", views.prepare_inputs),
]
