from django.urls import path
from . import views

urlpatterns = [
    path("content/articles/", views.articles),
    path("content/articles/<int:article_id>/", views.article_detail),
    path("content/articles/<int:article_id>/assets/", views.upload_asset),
    path("content/assets/<int:asset_id>/", views.asset_file),
]
