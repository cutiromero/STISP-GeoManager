from __future__ import annotations

from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.catalog.permissions import related_access_filter
from apps.core.api import api_login_required
from apps.core.permissions import feature_denied_response, has_feature_perm
from apps.omics.models import GermplasmAccession
from apps.omics.serializers import serialize_germplasm_accession


@require_GET
@api_login_required
def list_germplasm_accessions(request):
    if not has_feature_perm(request.user, "core.browse_data"):
        return feature_denied_response(request.user)

    parsed = _parse_pagination(request.GET)
    if "error" in parsed:
        return JsonResponse({"detail": parsed["error"]}, status=400)

    queryset = (
        GermplasmAccession.objects.select_related(
            "taxon",
            "source_site",
            "biological_sample",
            "biological_sample__taxon",
            "biological_sample__source_site",
            "source_resource",
        )
        .filter(related_access_filter(request.user, "source_resource"))
        .distinct()
    )
    queryset = _apply_filters(queryset, request.GET)
    if isinstance(queryset, JsonResponse):
        return queryset

    current = parsed["current"]
    page_size = parsed["page_size"]
    total = queryset.count()
    start = (current - 1) * page_size
    end = start + page_size
    items = [serialize_germplasm_accession(item) for item in queryset[start:end]]
    return JsonResponse(
        {
            "items": items,
            "total": total,
            "current": current,
            "pageSize": page_size,
        }
    )


def _parse_pagination(params) -> dict:
    current = _positive_int(params.get("current"), "current", default=1)
    if isinstance(current, str):
        return {"error": current}
    page_size = _positive_int(params.get("pageSize"), "pageSize", default=10)
    if isinstance(page_size, str):
        return {"error": page_size}
    return {"current": current, "page_size": page_size}


def _positive_int(raw_value: str | None, field_name: str, *, default: int) -> int | str:
    if raw_value in (None, ""):
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return f"{field_name} 必须为正整数"
    if value < 1:
        return f"{field_name} 必须为正整数"
    return value


def _apply_filters(queryset, params):
    keyword = (params.get("q") or "").strip()
    if keyword:
        queryset = queryset.filter(
            Q(accession_code__icontains=keyword)
            | Q(sample_code__icontains=keyword)
            | Q(resource_type__icontains=keyword)
            | Q(storage_status__icontains=keyword)
            | Q(raw_location__icontains=keyword)
            | Q(notes__icontains=keyword)
            | Q(source_site__name__icontains=keyword)
            | Q(source_site__raw_location__icontains=keyword)
            | Q(biological_sample__sample_code__icontains=keyword)
            | Q(biological_sample__raw_location__icontains=keyword)
        )

    taxon = (params.get("taxon") or "").strip()
    if taxon:
        queryset = queryset.filter(
            Q(taxon__name_cn__icontains=taxon)
            | Q(taxon__scientific_name__icontains=taxon)
            | Q(biological_sample__taxon__name_cn__icontains=taxon)
            | Q(biological_sample__taxon__scientific_name__icontains=taxon)
        )

    site = (params.get("site") or "").strip()
    if site:
        queryset = queryset.filter(
            Q(source_site__name__icontains=site)
            | Q(source_site__admin_region__icontains=site)
            | Q(source_site__raw_location__icontains=site)
            | Q(biological_sample__source_site__name__icontains=site)
            | Q(biological_sample__source_site__admin_region__icontains=site)
            | Q(biological_sample__source_site__raw_location__icontains=site)
        )

    if "isCore" in params:
        parsed = _parse_bool(params.get("isCore"))
        if parsed is None:
            return JsonResponse({"detail": "isCore 必须为布尔值"}, status=400)
        queryset = queryset.filter(is_core=parsed)

    return queryset


def _parse_bool(raw_value: str | None) -> bool | None:
    if raw_value is None:
        return None
    value = raw_value.strip().lower()
    if value in {"true", "1", "yes", "y"}:
        return True
    if value in {"false", "0", "no", "n"}:
        return False
    return None
