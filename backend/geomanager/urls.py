from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path, re_path

from apps.core.views import frontend_app
from apps.core.frontend_assets import historical_asset
from apps.ecology.monitoring_views import (
    monitoring,
    wildfire_catalog,
    official_monitoring,
    publish_monitoring,
)
from apps.ecology.source_catalog_views import (
    sources as monitoring_sources,
    times as monitoring_source_times,
)
from apps.ecology.source_preview_views import preview as monitoring_source_preview


urlpatterns = [
    path("api/ecology/monitoring/source-preview/", monitoring_source_preview),
    path(
        "api/ecology/monitoring/source-preview/<str:job_id>/", monitoring_source_preview
    ),
    path(
        "api/ecology/monitoring/source-preview/<str:job_id>/image/",
        monitoring_source_preview,
        {"image": True},
    ),
    path("api/ecology/monitoring/sources/", monitoring_sources),
    path("api/ecology/monitoring/source-times/", monitoring_source_times),
    path("api/ecology/monitoring/", monitoring),
    path("api/ecology/monitoring/official/", official_monitoring),
    path("api/ecology/monitoring/registration/", publish_monitoring),
    path("api/ecology/wildfire/catalog/", wildfire_catalog),
    path("api/business-flows/", include("apps.business_flows.urls")),
    re_path(r"^static/assets/(?P<asset_path>.+)$", historical_asset),
    path("api/knowledge/", include("apps.knowledge.urls")),
    path("api/agent/", include("apps.agent.urls")),
    path("api/compute/", include("apps.compute.urls")),
    path("api/", include("apps.projects.urls")),
    path("api/", include("apps.content.urls")),
    path("api/", include("apps.core.urls")),
    path("api/", include("apps.catalog.urls")),
    path("api/", include("apps.standards.urls")),
    path("api/germplasm/", include("apps.omics.urls")),
    path("api/raster/", include("apps.raster.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += [
    re_path(r"^(?!api/|static/|media/|admin2/).*$", frontend_app, name="frontend-app"),
]
