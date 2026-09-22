from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.core.api import api_login_required
from apps.core.permissions import feature_denied_response, has_feature_perm
from apps.standards.serializers import (
    catalog_tree,
    domain_definitions,
    schema_entities,
    schema_layers,
)
from apps.catalog.taxonomy import DATA_TAXONOMY_VERSION


@require_GET
@api_login_required
def data_schema_summary(request):
    if not has_feature_perm(request.user, "core.browse_data"):
        return feature_denied_response(request.user)
    return JsonResponse(
        {
            "taxonomyVersion": DATA_TAXONOMY_VERSION,
            "domains": domain_definitions(),
            "layers": schema_layers(),
            "entities": schema_entities(),
            "catalogTree": catalog_tree(),
        }
    )
