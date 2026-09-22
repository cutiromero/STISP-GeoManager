from django.urls import path

from apps.standards import views


urlpatterns = [
    path("data-schema/summary/", views.data_schema_summary, name="data-schema-summary"),
]
