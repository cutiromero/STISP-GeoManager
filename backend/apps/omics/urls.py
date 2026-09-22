from django.urls import path

from apps.omics import views


urlpatterns = [
    path("accessions/", views.list_germplasm_accessions, name="germplasm-accessions"),
]
