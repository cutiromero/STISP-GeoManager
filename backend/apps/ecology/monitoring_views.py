from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse

from apps.core.api import api_login_required
from apps.core.permissions import has_feature_perm, feature_denied_response
from apps.projects.context import require_live_membership
from .monitoring import MAX_PAGE, SCENES, monitoring_snapshot


@api_login_required
def monitoring(request):
    if request.method != "GET":
        return JsonResponse({"detail": "请求方法无效"}, status=405)
    if not has_feature_perm(request.user, "core.browse_data"):
        return feature_denied_response(request.user)
    try:
        if not request.headers.get("X-Project-Id"):
            raise ValidationError("请显式选择当前项目")
        require_live_membership()
        scene = request.GET.get("scene")
        if scene not in SCENES:
            raise ValidationError("请选择已配置的遥感场景")
        try:
            limit = int(request.GET.get("limit", str(MAX_PAGE)))
            before = int(request.GET["beforeId"]) if "beforeId" in request.GET else None
        except (ValueError, TypeError):
            raise ValidationError("分页参数须为整数")
        if not 1 <= limit <= MAX_PAGE or (before is not None and before <= 0):
            raise ValidationError("limit须为1至60，beforeId须为正整数")
        return JsonResponse(monitoring_snapshot(request.user, scene, before, limit))
    except ValidationError as error:
        return JsonResponse({"detail": "；".join(error.messages)}, status=400)
    except PermissionDenied as error:
        return JsonResponse({"detail": str(error)}, status=403)


@api_login_required
def wildfire_catalog(request):
    if request.method != "GET":
        return JsonResponse({"detail": "请求方法无效"}, status=405)
    if not has_feature_perm(request.user, "core.browse_data"):
        return feature_denied_response(request.user)
    try:
        if not request.headers.get("X-Project-Id"):
            raise ValidationError("请显式选择当前项目")
        require_live_membership()
        from .wildfire import observation_catalog

        return JsonResponse(observation_catalog(request.user))
    except ValidationError as error:
        return JsonResponse({"detail": "；".join(error.messages)}, status=400)
    except PermissionDenied as error:
        return JsonResponse({"detail": str(error)}, status=403)


@api_login_required
def official_monitoring(request):
    if request.method != "GET":
        return JsonResponse({"detail": "请求方法无效"}, status=405)
    if not has_feature_perm(request.user, "core.browse_data"):
        return feature_denied_response(request.user)
    try:
        if (
            not request.headers.get("X-Project-Id")
            or request.GET.get("scene") not in SCENES
        ):
            raise ValidationError("请选择当前项目及监测场景")
        require_live_membership()
        from .official_monitoring import official_snapshot

        return JsonResponse(official_snapshot(request.user, request.GET["scene"]))
    except ValidationError as error:
        return JsonResponse({"detail": "；".join(error.messages)}, status=400)
    except PermissionDenied as error:
        return JsonResponse({"detail": str(error)}, status=403)


@api_login_required
def publish_monitoring(request):
    from apps.compute.packages import ComputeError

    if request.method != "POST":
        return JsonResponse({"detail": "请求方法无效"}, status=405)
    try:
        if not request.headers.get("X-Project-Id"):
            raise ValidationError("请显式选择当前项目")
        require_live_membership()
        from apps.business_flows.views import body
        from .official_monitoring import register_output

        value = body(request, {"outputId"})
        identity = value.get("outputId")
        if type(identity) is not int or identity < 1:
            raise ValidationError("请选择有效的计算成果")
        product = register_output(request.user, identity)
        return JsonResponse(
            {"id": product.pk, "scene": product.metadata["monitoring"]["scene"]}
        )
    except ValidationError as error:
        return JsonResponse({"detail": "；".join(error.messages)}, status=400)
    except PermissionDenied as error:
        return JsonResponse({"detail": str(error)}, status=403)
    except ComputeError as error:
        return JsonResponse({"detail": str(error)}, status=error.status)
