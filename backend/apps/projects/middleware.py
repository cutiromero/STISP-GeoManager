import re

from django.core.exceptions import ValidationError
from django.http import JsonResponse, Http404
from django.utils.deprecation import MiddlewareMixin

from .context import ProjectScope, current_scope, is_superadmin
from .models import Project


PUBLIC_VIEWS = frozenset(
    {
        "data_schema_summary",
        "directories",
        "resources",
        "layers",
        "search",
        "resource_profile",
        "resource_visualization_summary_view",
        "resource_query",
        "resource_nongeo_analysis",
        "resource_nongeo_query",
        "workspaces",
        "workspace_detail",
        "map_compositions",
        "map_composition_detail",
        "map_composition_version_file",
        "result_artifacts",
        "result_artifact_detail",
        "result_artifact_file",
        "datasets",
        "tile",
        "render",
        "unique_values",
        "render_async",
        "job_status",
    }
)
PUBLIC_POST_VIEWS = frozenset(
    {
        "resource_query",
        "resource_nongeo_query",
        "render",
        "render_async",
        "unique_values",
    }
)

UPLOAD_PATHS = frozenset(
    {
        "/api/catalog/import/commit/",
        "/api/catalog/vector-import/commit/",
        "/api/raster/import/",
        "/api/catalog/results/",
    }
)


def public_read_request(request, view_name):
    return bool(
        view_name in PUBLIC_VIEWS
        and (request.method in {"GET", "HEAD"} or view_name in PUBLIC_POST_VIEWS)
        and getattr(request, "project_scope", None) is not None
        and request.project_scope.selected == 1
    )


class ProjectScopeMiddleware(MiddlewareMixin):
    def __call__(self, request):
        if not request.path.startswith("/api/") or request.path.startswith(
            ("/api/health/", "/api/bootstrap/")
        ):
            return self.get_response(request)
        header = request.headers.get("X-Project-Id", "")
        query = request.GET.get("projectTagId", "")
        if request.path.startswith("/api/content/"):
            # Published editorial content is platform-wide, including its media.
            header = query = ""
        if (
            request.user.is_authenticated
            and request.method == "POST"
            and request.path in UPLOAD_PATHS
            and not header
        ):
            return JsonResponse(
                {"detail": "上传前必须显式选择所属项目标签（公开项目为 1）"}, status=400
            )
        if header and query and header != query:
            return JsonResponse({"detail": "项目请求头与查询参数冲突"}, status=400)
        value = header or query or "1"
        if request.path.startswith(
            ("/api/auth/", "/api/projects/", "/api/bootstrap/", "/api/health/")
        ):
            value = "1"
        superadmin = is_superadmin(request.user)
        available = (
            Project.objects.all()
            if superadmin
            else Project.objects.filter(is_active=True)
            .filter(models_q(request.user))
            .distinct()
        )
        if value == "all":
            return JsonResponse(
                {"detail": "每次只能选择一个项目，不支持全部项目汇总"}, status=400
            )
        if not re.fullmatch(r"[1-9]\d*", value):
            return JsonResponse({"detail": "无效的项目标签"}, status=400)
        selected = int(value)
        if not available.filter(pk=selected).exists():
            return JsonResponse({"detail": "项目不存在或无权访问"}, status=404)
        ids = (selected,)
        public_read = request.path.startswith(
            (
                "/api/catalog/",
                "/api/raster/",
                "/api/data-schema/",
                "/api/content/",
                "/api/layers/",
                "/api/search/",
            )
        ) and (
            request.method in {"GET", "HEAD"}
            or request.path.endswith(
                (
                    "/query/",
                    "/nongeo-query/",
                    "/render/",
                    "/render/async/",
                    "/unique-values/",
                )
            )
        )
        request.project_scope = ProjectScope(
            ids, selected, getattr(request.user, "id", None), superadmin, public_read
        )
        token = current_scope.set(request.project_scope)
        try:
            response = self.get_response(request)
            # Private responses must be re-authorized after membership revocation.
            response["Vary"] = ", ".join(
                filter(None, [response.get("Vary"), "Cookie", "X-Project-Id"])
            )
            if selected != 1 or request.user.is_authenticated:
                response["Cache-Control"] = "private, no-store"
            return response
        finally:
            current_scope.reset(token)

    def process_exception(self, request, exception):
        if isinstance(exception, ValidationError):
            return JsonResponse({"detail": "；".join(exception.messages)}, status=400)
        if isinstance(exception, Http404):
            return JsonResponse({"detail": "对象不存在或无权访问"}, status=404)


def models_q(user):
    from django.db.models import Q

    query = Q(is_default=True)
    if user.is_authenticated and user.is_active:
        query |= Q(memberships__user=user)
    return query
