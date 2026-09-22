from functools import wraps

from django.http import JsonResponse

from apps.core.permissions import has_feature_perm
from apps.core.localization import localized


def csrf_failure(request, reason=""):
    return JsonResponse(
        {"detail": localized("CSRF 验证失败", "CSRF validation failed")},
        status=403,
    )


def api_login_required(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        from apps.projects.middleware import public_read_request

        if not request.user.is_authenticated and not public_read_request(
            request, view_func.__name__
        ):
            return JsonResponse(
                {"detail": localized("请先登录", "Sign in first")}, status=401
            )
        return view_func(request, *args, **kwargs)

    return wrapped


def api_permission_required(perm_name: str):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return JsonResponse(
                    {"detail": localized("请先登录", "Sign in first")}, status=401
                )
            if not has_feature_perm(request.user, perm_name):
                return JsonResponse(
                    {
                        "detail": localized(
                            "当前用户无后台管理权限",
                            "Your account does not have administrative access",
                        )
                    },
                    status=403,
                )
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


def api_any_permission_required(*perm_names: str):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return JsonResponse(
                    {"detail": localized("请先登录", "Sign in first")}, status=401
                )
            if not any(has_feature_perm(request.user, perm) for perm in perm_names):
                return JsonResponse(
                    {
                        "detail": localized(
                            "当前用户无后台管理权限",
                            "Your account does not have administrative access",
                        )
                    },
                    status=403,
                )
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
