from django.http import JsonResponse

from apps.projects.context import selected_project_id
from .capability_catalog import catalog
from .views import endpoint


@endpoint(["GET"])
def capabilities(request):
    return JsonResponse(catalog(request.user, selected_project_id()))
