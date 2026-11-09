from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path, re_path

from apps.core.views import frontend_app
from apps.core.frontend_assets import historical_asset


urlpatterns = [
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
