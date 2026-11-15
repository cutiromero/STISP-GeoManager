"""Friendly monitoring source selection; internal ordinals stay behind dates."""

from functools import wraps
from django.core.exceptions import ValidationError, PermissionDenied
from django.http import JsonResponse
from apps.core.api import api_login_required
from apps.core.permissions import has_feature_perm
from apps.projects.context import require_live_membership
from .source_catalog import monitoring_sources, source_times


def endpoint(function):
    @api_login_required
    @wraps(function)
    def call(request):
        if request.method != "GET":
            return JsonResponse({"detail": "请求方法无效"}, status=405)
        try:
            if not request.headers.get("X-Project-Id"):
                raise ValidationError("请显式选择当前项目")
            require_live_membership()
            if not has_feature_perm(request.user, "core.browse_data"):
                raise PermissionDenied("当前用户无数据浏览权限")
            value = function(request)
            response = JsonResponse(value)
            response["Cache-Control"] = "private, no-store"
            return response
        except ValidationError as error:
            return JsonResponse({"detail": "；".join(error.messages)}, status=400)
        except PermissionDenied as error:
            return JsonResponse({"detail": str(error)}, status=403)
        except (TypeError, ValueError):
            return JsonResponse({"detail": "日期或分页参数无效"}, status=400)

    return call


@endpoint
def sources(request):
    return monitoring_sources(
        request.user,
        request.GET.get("scene"),
        offset=int(request.GET.get("offset", 0)),
        collection=request.GET.get("collection"),
        year=int(request.GET["year"]) if request.GET.get("year") else None,
    )


@endpoint
def times(request):
    return source_times(
        request.user,
        request.GET.get("scene"),
        int(request.GET.get("resourceId", 0)),
        int(request.GET["year"]) if request.GET.get("year") else None,
        request.GET.get("product"),
        int(request.GET["after"]) if request.GET.get("after") else None,
        int(request.GET.get("limit", 500)),
    )
