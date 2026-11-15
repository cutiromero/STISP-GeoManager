import json
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse, FileResponse
from apps.core.api import api_login_required
from apps.raster.services.exceptions import RasterJobError
from .source_preview import request_preview, readable_job, job_payload


@api_login_required
def preview(request, job_id=None, image=False):
    try:
        if not request.headers.get("X-Project-Id"):
            raise ValidationError("请显式选择当前项目")
        if job_id:
            if request.method != "GET":
                return JsonResponse({"detail": "请求方法无效"}, status=405)
            job = readable_job(request.user, job_id)
            if image:
                if job.status != "ready":
                    raise ValidationError("原始图层预览尚未就绪")
                response = FileResponse(
                    open(job.artifact_path, "rb"), content_type="image/png"
                )
            else:
                response = JsonResponse(job_payload(job))
        else:
            if request.method != "POST":
                return JsonResponse({"detail": "请求方法无效"}, status=405)
            if len(request.body) > 2048:
                raise ValidationError("预览请求过大")
            data = json.loads(request.body)
            if (
                not isinstance(data, dict)
                or type(data.get("ordinal")) is not int
                or type(data.get("resourceId")) is not int
            ):
                raise ValidationError("资料或时期参数无效")
            job = request_preview(
                request.user,
                data.get("scene"),
                data["resourceId"],
                data.get("product"),
                data["ordinal"],
            )
            response = JsonResponse(job_payload(job), status=202)
        response["Cache-Control"] = "private, no-store"
        return response
    except PermissionDenied as error:
        return JsonResponse({"detail": str(error)}, status=403)
    except (
        ValidationError,
        ValueError,
        TypeError,
        RasterJobError,
        FileNotFoundError,
    ) as error:
        return JsonResponse({"detail": str(error)}, status=400)
