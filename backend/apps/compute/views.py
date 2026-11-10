from functools import wraps
from functools import lru_cache
from pathlib import Path
import json
import logging
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Case, When, Value, IntegerField, Q, Prefetch
from django.conf import settings
from django.db.models.deletion import ProtectedError
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from apps.audit.service import log_operation
from apps.catalog.models import DataResource, task_resource_q
from apps.catalog.permissions import filter_accessible
from apps.core.storage import app_path
from .access import permission, project_id, require_actor, task_access
from apps.raster.models import RasterDataset
from .data import list_candidate, preview
from .models import (
    AlgorithmCategory,
    AlgorithmResource,
    AlgorithmVersion,
    ComputeTask,
    ComputeOutput,
)
from .packages import ComputeError, IDENTIFIER, checksum, clean_text, inspect_package
from .serializers import algorithm_data, version_data, task_data, output_data
from .services import (
    allowed_algorithms,
    runtime_state,
    submit,
    task_action,
    validate_submission,
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def builtin_search_labels():
    path = Path(settings.PROGRAM_ROOT) / "frontend/src/compute/builtin.en.json"
    return json.loads(path.read_text(encoding="utf-8"))


def endpoint(methods, public=False):
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            try:
                if not public or request.method != "GET":
                    require_actor(request.user, project_id())
                if request.method != "GET" and not request.headers.get("X-Project-Id"):
                    raise ComputeError("写入前必须显式选择所属项目标签")
                return view(request, *args, **kwargs)
            except ComputeError as exc:
                return JsonResponse({"detail": str(exc)}, status=exc.status)
            except ValidationError as exc:
                return JsonResponse({"detail": "；".join(exc.messages)}, status=400)
            except IntegrityError:
                return JsonResponse(
                    {"detail": "标识或版本已存在，请刷新后重试"}, status=409
                )

        return require_http_methods(methods)(wrapped)

    return decorate


def payload(request):
    try:
        body = json.loads(request.body)
        if not isinstance(body, dict):
            raise ValueError()
        return body
    except (ValueError, UnicodeError) as exc:
        raise ComputeError("请求必须是有效JSON对象") from exc


def page(request, query, serialize):
    try:
        index = max(1, int(request.GET.get("page", "1")))
        size = max(1, min(50, int(request.GET.get("pageSize", "20"))))
    except ValueError as exc:
        raise ComputeError("分页参数必须为整数") from exc
    return JsonResponse(
        {
            "items": [
                serialize(item) for item in query[(index - 1) * size : index * size]
            ],
            "total": query.count(),
        }
    )


def audit(request, action, name=""):
    log_operation(request.user, "计算中心", action, "success", name, request)


def managed_algorithm(user, algorithm_id):
    require_actor(user, project_id(), "manage_algorithms")
    return get_object_or_404(AlgorithmResource.objects, pk=algorithm_id)


@endpoint(["GET"])
def runtime(request):
    return JsonResponse(runtime_state(request.user))


@endpoint(["GET", "POST"], public=True)
def categories(request):
    if request.method == "POST":
        require_actor(request.user, project_id(), "manage_algorithms")
        body = payload(request)
        name = clean_text(body.get("name"), 80, "分类名称")
        order = body.get("sortOrder", 100)
        if type(order) is not int or not 0 <= order <= 10000:
            raise ComputeError("分类排序必须为0至10000的整数")
        item = AlgorithmCategory.objects.create(name=name, sort_order=order)
        audit(request, "新增算法分类", name)
        return JsonResponse(
            {"id": item.id, "name": item.name, "sortOrder": item.sort_order}
        )
    query = AlgorithmCategory._base_manager.filter(
        project_tag_id__in={1, project_id()}
    ).order_by("sort_order", "id")
    if project_id() != 1:
        query = query.filter(
            Q(project_tag_id=project_id())
            | Q(name__in=allowed_algorithms().values_list("category", flat=True))
        )
    return JsonResponse(
        {
            "items": [
                {"id": item.id, "name": item.name, "sortOrder": item.sort_order}
                for item in query
            ],
            "total": query.count(),
        }
    )


def algorithm_values(body):
    identifier = clean_text(body.get("identifier"), 80, "算法标识")
    if not IDENTIFIER.fullmatch(identifier):
        raise ComputeError(
            "算法标识须为小写英文字母开头，后接字母、数字、下划线或短横线"
        )
    enabled = body.get("enabled", True)
    if type(enabled) is not bool:
        raise ComputeError("enabled 必须为布尔值")
    return {
        "identifier": identifier,
        "name": clean_text(body.get("name"), 160, "算法名称"),
        "description": clean_text(body.get("description", ""), 4000, "说明", False),
        "category": clean_text(body.get("category", ""), 80, "分类", False),
        "author": clean_text(body.get("author", ""), 160, "作者", False),
        "enabled": enabled,
    }


@endpoint(["GET", "POST"], public=True)
def algorithms(request):
    if request.method == "POST":
        require_actor(request.user, project_id(), "manage_algorithms")
        algorithm = AlgorithmResource.objects.create(
            **algorithm_values(payload(request)), created_by=request.user
        )
        audit(request, "登记算法", algorithm.name)
        return JsonResponse(algorithm_data(algorithm, request.user))
    query = allowed_algorithms()
    if request.GET.get("manage") == "1":
        require_actor(request.user, project_id(), "manage_algorithms")
        query = query.filter(project_tag_id=project_id())
    else:
        query = query.filter(enabled=True, versions__status="published").distinct()
    if request.GET.get("q"):
        term = request.GET["q"][:160]
        translated = [
            zh
            for zh, en in builtin_search_labels().items()
            if term.casefold() in en.casefold()
        ]
        query = query.filter(Q(name__icontains=term) | Q(name__in=translated))
    if request.GET.get("category"):
        query = query.filter(category=request.GET["category"])
    categories = AlgorithmCategory._base_manager.filter(
        project_tag_id__in={1, project_id()}
    ).order_by("sort_order", "id")
    orders = {}
    for category in categories:
        orders.setdefault(category.name, category.sort_order)
    query = query.annotate(
        category_order=Case(
            *[When(category=name, then=Value(order)) for name, order in orders.items()],
            default=Value(999999),
            output_field=IntegerField(),
        )
    )
    return page(
        request,
        query.order_by("category_order", "category", "name", "id"),
        lambda a: algorithm_data(a, request.user),
    )


def remove_algorithm_packages(paths):
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Unable to remove deleted algorithm package %s", path)


@endpoint(["POST", "DELETE"])
def algorithm_detail(request, algorithm_id):
    algorithm = managed_algorithm(request.user, algorithm_id)
    if request.method == "DELETE":
        try:
            with transaction.atomic():
                if ComputeTask._base_manager.filter(
                    version__algorithm_id=algorithm.id
                ).exists():
                    raise ComputeError("已有任务记录的算法不能删除，请归档停用", 409)
                paths = [app_path(v.package_path) for v in algorithm.versions.all()]
                algorithm.versions.all().delete()
                algorithm.delete()
                audit(request, "删除算法", algorithm.name)
                # Keep files intact if an enclosing transaction rolls back.
                transaction.on_commit(lambda: remove_algorithm_packages(paths))
        except ProtectedError as exc:
            raise ComputeError("已有任务记录的算法不能删除，请归档停用", 409) from exc
        return JsonResponse({"detail": "算法已删除"})
    values = algorithm_values(payload(request))
    if algorithm.versions.exists() and values["identifier"] != algorithm.identifier:
        raise ComputeError("已有版本的算法不能修改稳定标识")
    for key, value in values.items():
        setattr(algorithm, key, value)
    algorithm.save()
    audit(request, "更新算法", algorithm.name)
    return JsonResponse(algorithm_data(algorithm, request.user))


def store_version(algorithm, upload):
    if upload.size > 50 * 1024**2:
        raise ComputeError("算法包不能超过50 MiB")
    directory = app_path(
        "projects",
        str(algorithm.project_tag_id),
        "compute",
        "algorithms",
        str(algorithm.id),
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (uuid.uuid4().hex + ".zip")
    try:
        with path.open("xb") as stream:
            total = 0
            for chunk in upload.chunks():
                total += len(chunk)
                if total > 50 * 1024**2:
                    raise ComputeError("算法包不能超过50 MiB")
                stream.write(chunk)
        manifest = inspect_package(path)
        if manifest["identifier"] != algorithm.identifier:
            raise ComputeError("清单 identifier 必须与登记的算法标识相同")
        with transaction.atomic():
            item = AlgorithmVersion.objects.create(
                algorithm=algorithm,
                version=manifest["version"],
                manifest=manifest,
                checksum=checksum(path),
                package_path=path.relative_to(app_path()).as_posix(),
            )
        return item
    except Exception:
        path.unlink(missing_ok=True)
        raise


@endpoint(["POST"])
def versions(request, algorithm_id):
    algorithm = managed_algorithm(request.user, algorithm_id)
    upload = request.FILES.get("file")
    if not upload:
        raise ComputeError("请选择ZIP算法包")
    version = store_version(algorithm, upload)
    audit(request, "上传算法版本", algorithm.name + " " + version.version)
    return JsonResponse(version_data(version))


@endpoint(["POST"])
def version_action(request, version_id):
    version = get_object_or_404(
        AlgorithmVersion.objects.select_related("algorithm"), pk=version_id
    )
    managed_algorithm(request.user, version.algorithm_id)
    action = payload(request).get("action")
    if action == "publish":
        require_actor(request.user, project_id(), "publish_algorithm")
        if version.status == "archived":
            raise ComputeError("归档版本不能重新发布，请新增版本", 409)
        if (
            not version.runtime_digest
            or not ComputeTask.objects.filter(
                version=version, trial=True, status="succeeded"
            ).exists()
        ):
            raise ComputeError("发布前必须完成一次隔离试运行，并通过结果检查", 409)
        version.status = "published"
    elif action == "archive":
        version.status = "archived"
    else:
        raise ComputeError("不支持该版本操作")
    version.save(update_fields=["status"])
    audit(
        request,
        "发布算法版本" if action == "publish" else "归档算法版本",
        version.algorithm.name + " " + version.version,
    )
    return JsonResponse(version_data(version))


def file_response(path, name):
    if not path.is_file():
        raise ComputeError("文件已过期或不存在", 404)
    response = FileResponse(
        path.open("rb"),
        as_attachment=True,
        filename=name,
        content_type="application/octet-stream",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@endpoint(["GET"])
def package_file(request, version_id):
    require_actor(request.user, project_id(), "download_algorithm")
    version = get_object_or_404(
        AlgorithmVersion.objects.filter(algorithm__in=allowed_algorithms()),
        pk=version_id,
    )
    if version.status != "published" and not (
        permission(request.user, "manage_algorithms")
        and version.algorithm.project_tag_id == project_id()
    ):
        raise ComputeError("无权下载该版本", 404)
    audit(request, "下载算法包", version.algorithm.name + " " + version.version)
    return file_response(
        app_path(version.package_path),
        version.algorithm.identifier + "-" + version.version + ".zip",
    )


@endpoint(["GET"])
def template_file(request, template_id):
    require_actor(request.user, project_id(), "manage_algorithms")
    from .templates import build_package

    package, name = build_package(template_id)
    import io

    return FileResponse(
        io.BytesIO(package),
        as_attachment=True,
        filename=name + ".zip",
        content_type="application/zip",
    )


@endpoint(["GET"])
def inputs(request):
    require_actor(request.user, project_id(), "submit_task", "core.browse_data")
    query = filter_accessible(
        DataResource.objects.filter(
            status="active", data_type__in=["raster", "vector", "table"]
        ),
        request.user,
    ).order_by("-id")
    if request.GET.get("resourceId"):
        try:
            resource_id = int(request.GET["resourceId"])
        except ValueError as exc:
            raise ComputeError("资源编号必须为整数") from exc
        query = query.filter(pk=resource_id)
    else:
        query = query.exclude(task_resource_q())
    if request.GET.get("kind"):
        query = query.filter(data_type=request.GET["kind"])
    if request.GET.get("q"):
        query = query.filter(name__icontains=request.GET["q"][:160])
    query = query.prefetch_related(
        Prefetch(
            "raster_datasets",
            queryset=RasterDataset.objects.filter(status="ready").only(
                "data_resource_id", "source_relative_path", "source_gdalinfo"
            ),
            to_attr="_compute_ready_rasters",
        )
    )
    return page(request, query, list_candidate)


@endpoint(["POST"])
def preflight(request):
    data = validate_submission(request.user, payload(request))
    return JsonResponse(
        {
            "valid": True,
            "parameters": data["parameters"],
            "detail": "权限、类型和参数检查通过；提交后将固定输入并进行完整文件检查",
        }
    )


@endpoint(["GET", "POST"])
def tasks(request):
    if request.method == "POST":
        task = submit(request.user, payload(request))
        audit(request, "提交计算", task.name)
        return JsonResponse(task_data(task))
    query = ComputeTask.objects.select_related("owner", "version__algorithm").order_by(
        "-created_at"
    )
    if request.GET.get("manage") == "1":
        require_actor(request.user, project_id(), "manage_tasks")
    else:
        require_actor(request.user, project_id(), "view_own_task")
        query = query.filter(owner=request.user)
    if request.GET.get("status"):
        query = query.filter(status=request.GET["status"])
    if request.GET.get("q"):
        query = query.filter(name__icontains=request.GET["q"][:160])
    return page(request, query, task_data)


@endpoint(["GET", "POST"])
def task_detail(request, task_id):
    task = get_object_or_404(
        ComputeTask.objects.select_related("owner", "version__algorithm"), pk=task_id
    )
    task_access(task, request.user)
    if request.method == "POST":
        action = payload(request).get("action")
        task = task_action(task, request.user, action)
        audit(request, "任务操作 " + str(action), task.name)
    return JsonResponse(task_data(task))


def authorized_output(request, output_id):
    output = get_object_or_404(
        ComputeOutput.objects.select_related(
            "task__owner", "task__version__algorithm"
        ).filter(task__project_tag_id=project_id()),
        pk=output_id,
    )
    try:
        task_access(output.task, request.user)
    except ComputeError:
        from apps.catalog.share_access import can_read_shared_output

        if not can_read_shared_output(output, request.user):
            raise
    if output.expired:
        raise ComputeError("临时结果已过期；已入库的数据仍可在数据资源中访问", 404)
    return output


@endpoint(["GET"])
def output_file(request, output_id):
    output = authorized_output(request, output_id)
    require_actor(request.user, project_id(), "catalog.export_dataresource")
    audit(request, "下载计算结果", output.label)
    return file_response(app_path(output.path), output.file_name)


@endpoint(["GET"])
def output_preview(request, output_id):
    output = authorized_output(request, output_id)
    view = request.GET.get("view", "table")
    if view not in {"table", "map"}:
        raise ComputeError("结果预览视图无效")
    return JsonResponse(preview(output, view=view))


def authorized_map_output(request, output_id):
    output = authorized_output(request, output_id)
    require_actor(request.user, project_id(), "core.browse_data")
    resources = [item.resource_id for item in output.task.input_records.all()]
    visible = filter_accessible(
        DataResource.objects.filter(pk__in=resources, status="active"),
        request.user,
    ).values_list("id", flat=True)
    if set(resources) != set(visible):
        raise ComputeError(
            "\u8ba1\u7b97\u8f93\u5165\u7684\u8bbf\u95ee\u6743\u9650\u5df2\u64a4\u56de",
            403,
        )
    return output


@endpoint(["GET"])
def output_map_preview(request, output_id):
    from .map_preview import ensure_map_preview

    output = authorized_map_output(request, output_id)
    band = map_preview_band(request)
    _, metadata = ensure_map_preview(output, band)
    return JsonResponse(
        {
            "name": output.task.name + " \u00b7 " + output.label,
            "kind": "raster",
            "metadata": {**output.metadata, **metadata},
            "temporary": True,
            "imageUrl": f"/api/compute/outputs/{output.id}/map-preview/image/?projectTagId={output.task.project_tag_id}&band={band}",
            "imageCoordinates": metadata["imageCoordinates"],
        }
    )


@endpoint(["GET"])
def output_map_image(request, output_id):
    from .map_preview import ensure_map_preview

    output = authorized_map_output(request, output_id)
    image, _ = ensure_map_preview(output, map_preview_band(request))
    response = HttpResponse(image, content_type="image/png")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


def map_preview_band(request):
    try:
        band = int(request.GET.get("band", "1"))
    except (TypeError, ValueError) as exc:
        raise ComputeError("地图预览波段须为整数") from exc
    if not 1 <= band <= 1024:
        raise ComputeError("地图预览波段须为1至1024")
    return band


@endpoint(["POST"])
def output_import(request, output_id):
    from .services import request_output_import

    output = authorized_output(request, output_id)
    require_actor(request.user, project_id(), "catalog.add_dataresource")
    if output.kind == "archive":
        raise ComputeError("多文件结果请下载解压后，按数据格式分别导入")
    body = payload(request)
    name = clean_text(
        body.get("name") or output.task.name + " " + output.label, 160, "入库名称"
    )
    request_output_import(request.user, output, name)
    audit(request, "计算结果申请入库", name)
    return JsonResponse(output_data(output))
