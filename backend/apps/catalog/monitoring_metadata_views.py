"""Project-scoped usage and scientific time metadata for registered resources."""

import json
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from apps.core.api import api_login_required
from apps.core.permissions import has_feature_perm
from apps.projects.context import require_live_membership
from .monitoring_metadata import metadata_batch, readable_resource, update_metadata

# CONFIGURATION
MAX_IDS = 100
MAX_BODY_BYTES = 16384


def _access(request):
    if not request.headers.get("X-Project-Id"):
        raise ValidationError("请显式选择当前项目")
    require_live_membership()
    if not has_feature_perm(request.user, "core.browse_data"):
        raise PermissionDenied("当前用户无数据浏览权限")


@api_login_required
def observation_metadata(request, resource_id):
    if request.method not in ["GET", "PATCH"]:
        return JsonResponse({"detail": "请求方法无效"}, status=405)
    try:
        _access(request)
        resource = readable_resource(request.user, resource_id)
        if resource is None:
            return JsonResponse({"detail": "数据资源不存在"}, status=404)
        if request.method == "PATCH":
            if len(request.body) > MAX_BODY_BYTES:
                raise ValidationError("资料元信息请求过大")
            try:
                data = json.loads(request.body)
            except (ValueError, UnicodeError) as error:
                raise ValidationError("请求JSON格式无效") from error
            value = update_metadata(request.user, resource, data)
        else:
            value = metadata_batch(request.user, [resource.pk])[0]
        response = JsonResponse(value)
        response["Cache-Control"] = "private, no-store"
        return response
    except ValidationError as error:
        return JsonResponse({"detail": "；".join(error.messages)}, status=400)
    except PermissionDenied as error:
        return JsonResponse({"detail": str(error)}, status=403)


@api_login_required
def observation_metadata_batch(request):
    if request.method != "GET":
        return JsonResponse({"detail": "请求方法无效"}, status=405)
    try:
        _access(request)
        raw = request.GET.get("ids", "")
        try:
            identities = list(
                dict.fromkeys(int(value) for value in raw.split(",") if value)
            )
        except ValueError as error:
            raise ValidationError("资源编号无效") from error
        if not 1 <= len(identities) <= MAX_IDS or any(
            value <= 0 for value in identities
        ):
            raise ValidationError("每次请选择1至100项资料")
        response = JsonResponse({"items": metadata_batch(request.user, identities)})
        response["Cache-Control"] = "private, no-store"
        return response
    except ValidationError as error:
        return JsonResponse({"detail": "；".join(error.messages)}, status=400)
    except PermissionDenied as error:
        return JsonResponse({"detail": str(error)}, status=403)
