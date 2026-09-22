import tomllib

from django.conf import settings
from django.http import Http404
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.catalog.models import DataResource, DictionaryItem, MapLayer
from apps.core.config import APP_SUBDIRS, RESEARCH_SUBDIRS
from apps.core.config import (
    load_runtime_config_document,
    sanitized_public_map_credentials,
)
from apps.core.map_thumbnail import ThumbnailTileError, thumbnail_tile
from apps.core.models import SystemSetting
from apps.core.localization import localized
from apps.core.platform_brand import (
    PLATFORM_ABBREVIATION,
    PLATFORM_EDITION,
    PLATFORM_ENGLISH_NAME,
)
from apps.core.runtime_config import (
    runtime_allow_registration,
    runtime_system_name,
    runtime_upload_max_mb,
)


def registration_allowed() -> bool:
    system_setting = (
        SystemSetting.objects.filter(pk=1).only("allow_registration").first()
    )
    if system_setting is None:
        return runtime_allow_registration()
    return system_setting.allow_registration


@require_GET
def bootstrap(request):
    config = settings.PROJECT_CONFIG
    runtime_document = load_runtime_config_document(config)
    application = runtime_document["application"]
    mapbox_token, tianditu_key = sanitized_public_map_credentials(application["map"])
    return JsonResponse(
        {
            "systemName": runtime_system_name(),
            "allowRegistration": registration_allowed(),
            "map": {
                "defaultCenter": application["map"]["default_center"],
                "defaultZoom": application["map"]["default_zoom"],
                "defaultBasemap": application["map"]["default_basemap"],
                "mapboxAccessToken": mapbox_token,
                "tiandituAccessToken": tianditu_key,
            },
            "limits": {
                "uploadMaxMb": runtime_upload_max_mb(),
                "queryResultLimit": application["limits"]["query_result_limit"],
                "maxRasterSidePixels": application["limits"]["max_raster_side_pixels"],
            },
        }
    )


@require_GET
def login_overview(request):
    generated_at = timezone.localtime().isoformat()
    metrics = _login_overview_metrics(generated_at)
    service_status = _login_overview_service_status(
        data_resources=metrics[0]["value"],
        thematic_layers=metrics[1]["value"],
    )

    return JsonResponse(
        {
            "generatedAt": generated_at,
            "platform": {
                "chineseName": runtime_system_name(),
                "englishName": PLATFORM_ENGLISH_NAME,
                "abbreviation": PLATFORM_ABBREVIATION,
                "edition": PLATFORM_EDITION,
                "version": _application_version(),
            },
            "hero": {
                "badge": localized(
                    "生态智慧监测平台",
                    "Ecological Intelligent Monitoring Platform",
                ),
                "summary": localized(
                    (
                        "平台集成遥感影像、空间矢量、野外样方、长期监测与生态专题数据，"
                        "提供统一编目、三维地理可视化、综合查询分析和共享服务。"
                    ),
                    (
                        "The platform integrates remote-sensing imagery, spatial vectors, "
                        "field plots, long-term monitoring, and ecological thematic data, "
                        "with unified cataloging, 3D geovisualization, query, analysis, and sharing."
                    ),
                ),
                "capabilityTags": [
                    localized("遥感影像", "Remote sensing imagery"),
                    localized("矢量边界", "Vector boundaries"),
                    localized("野外样方", "Field plots"),
                    localized("长期监测", "Long-term monitoring"),
                    localized("生态专题", "Ecological themes"),
                ],
            },
            "metrics": metrics,
            "serviceStatus": service_status,
            "footer": {
                "statisticsNotice": localized(
                    "统计口径已接入后端平台概览接口",
                    "Statistics are supplied by the live platform overview API",
                ),
            },
        }
    )


@require_GET
def health(request):
    return JsonResponse(
        {
            "status": "ok",
            "configLoaded": True,
            "configFormat": "toml",
            "appSubdirs": list(APP_SUBDIRS),
            "researchSubdirs": list(RESEARCH_SUBDIRS),
        }
    )


@require_GET
def map_thumbnail_tile(request, z: int, x: int, y: int):
    purpose = request.GET.get("purpose", "thumbnail")
    if purpose not in {"thumbnail", "export"}:
        return JsonResponse(
            {"detail": "purpose 必须为 thumbnail 或 export"}, status=400
        )
    try:
        data, content_type, is_fallback = thumbnail_tile(
            z,
            x,
            y,
            allow_fallback=purpose == "thumbnail",
            **(
                {
                    "basemap": request.GET["basemap"],
                    "labels": request.GET.get("labels") == "1",
                }
                if "basemap" in request.GET
                else {}
            ),
        )
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    except ThumbnailTileError:
        response = JsonResponse(
            {
                "detail": "制图底图服务暂时不可用，请稍后重试或检查服务器到 Mapbox/OSM 的网络连接"
            },
            status=503,
        )
        response["Cache-Control"] = "no-store"
        response["Retry-After"] = "2"
        return response

    response = HttpResponse(data, content_type=content_type)
    response["Cache-Control"] = (
        "public, max-age=60" if is_fallback else "public, max-age=86400"
    )
    return response


@require_GET
def frontend_app(request):
    index_path = settings.FRONTEND_DIST / "index.html"
    if (
        not index_path.exists()
        and not settings.STATIC_ROOT.joinpath("index.html").exists()
    ):
        raise Http404("前端构建产物不存在，请先运行 pnpm build")
    return render(request, "index.html")


def _login_overview_metrics(generated_at: str) -> list[dict]:
    active_resources = DataResource.objects.filter(status=DataResource.Status.ACTIVE)
    active_layers = MapLayer.objects.filter(is_active=True)
    covered_regions = DictionaryItem.objects.filter(
        dict_type=DictionaryItem.DictType.REGION,
        is_active=True,
    ).count()
    if covered_regions == 0:
        covered_regions = (
            active_resources.exclude(spatial_extent="")
            .values("spatial_extent")
            .distinct()
            .count()
        )

    metric_values = [
        (
            "dataResources",
            localized("平台数据资源", "Data resources"),
            active_resources.count(),
            localized(
                "平台已接入总量，登录后按权限显示",
                "Platform total; visibility follows account permissions",
            ),
        ),
        (
            "thematicLayers",
            localized("专题图层", "Thematic layers"),
            active_layers.count(),
            localized("生态保护专题", "Ecological conservation themes"),
        ),
        (
            "monitoringSites",
            localized("监测站点", "Monitoring sites"),
            active_layers.filter(geometry_type=MapLayer.GeometryType.POINT).count(),
            localized("长期观测网络", "Long-term observation network"),
        ),
        (
            "coveredBasins",
            localized("覆盖流域", "Covered basins"),
            covered_regions,
            localized("中亚重点区域", "Priority arid-region areas"),
        ),
    ]
    return [
        {
            "id": metric_id,
            "label": label,
            "value": value,
            "displayValue": _format_metric_value(value),
            "note": note,
            "updatedAt": generated_at,
        }
        for metric_id, label, value, note in metric_values
    ]


def _login_overview_service_status(
    *,
    data_resources: int,
    thematic_layers: int,
) -> dict:
    services = [
        {
            "id": "resourceCatalog",
            "label": localized("资源目录", "Resource catalog"),
            "status": "normal" if data_resources > 0 else "warning",
            "description": (
                localized(
                    f"已接入 {data_resources} 项启用数据资源。",
                    f"{data_resources} active data resources are connected.",
                )
                if data_resources > 0
                else localized(
                    "暂无启用数据资源，登录后可由管理员导入。",
                    "No active data resources are available; an administrator can import them after signing in.",
                )
            ),
        },
        {
            "id": "layerService",
            "label": localized("图层服务", "Layer service"),
            "status": "normal" if thematic_layers > 0 else "warning",
            "description": (
                localized(
                    f"地图图层服务当前可用，已配置 {thematic_layers} 个启用图层。",
                    f"The map layer service is available with {thematic_layers} active layers.",
                )
                if thematic_layers > 0
                else localized(
                    "暂无启用图层，登录后可由管理员配置。",
                    "No active layers are configured; an administrator can configure them after signing in.",
                )
            ),
        },
        {
            "id": "permissionGateway",
            "label": localized("权限认证", "Authorization"),
            "status": "normal",
            "description": localized(
                "统一身份认证与权限控制已开启。",
                "Unified authentication and permission controls are enabled.",
            ),
        },
    ]
    node_summary = _login_overview_node_summary(services)
    return {
        "title": localized("平台服务状态", "Platform service status"),
        "headline": _service_status_headline(services),
        "description": localized(
            "登录后可按账号权限进入数据目录和地图工作台；具备运维权限时显示后台管理入口。",
            "After signing in, the data catalog, geo workspace, and administration entry are shown according to account permissions.",
        ),
        "services": services,
        "nodeSummary": node_summary,
    }


def _login_overview_node_summary(services: list[dict]) -> dict:
    total = len(services)
    risk = sum(1 for service in services if service["status"] == "risk")
    warning = sum(1 for service in services if service["status"] == "warning")
    normal = sum(1 for service in services if service["status"] == "normal")
    return {
        "total": total,
        "normal": normal,
        "warning": warning,
        "risk": risk,
        "legend": [
            {
                "status": "normal",
                "label": localized("正常", "Normal"),
                "count": normal,
            },
            {
                "status": "warning",
                "label": localized("待同步", "Pending"),
                "count": warning,
            },
            {
                "status": "risk",
                "label": localized("异常", "Issue"),
                "count": risk,
            },
        ],
    }


def _service_status_headline(services: list[dict]) -> str:
    status_text = {
        "normal": localized("可用", " available"),
        "warning": localized("待同步", " pending"),
        "risk": localized("异常", " issue"),
    }
    return " · ".join(
        f"{service['label']}{status_text.get(service['status'], localized('未知', ' unknown'))}"
        for service in services
    )


def _format_metric_value(value: int) -> str:
    return f"{value:,}"


def _application_version() -> str:
    pyproject_path = settings.PROGRAM_ROOT / "backend" / "pyproject.toml"
    with pyproject_path.open("rb") as file:
        version = tomllib.load(file)["project"]["version"]
    return f"v{version}"
