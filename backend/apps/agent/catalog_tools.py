"""Exact scoped catalog counts and resumable resource discovery."""

import json

from django.core.exceptions import ValidationError
from django.db.models import Count, Q, Sum


def catalog_query(queryset, args):
    query = args.get("query", "")
    if not isinstance(query, str) or len(query) > 200:
        raise ValidationError("query 必须为不超过200字的字符串")
    text_query = Q(name__icontains=query) | Q(description__icontains=query)
    if any(
        word in query.lower()
        for word in ("table", "csv", "tsv", "xls", "excel", "表格", "数据表")
    ):
        text_query |= Q(data_type="table")
    queryset = queryset.filter(text_query)
    category = args.get("category", "all")
    if category not in {"all", "compute_results", "uploaded_data"}:
        raise ValidationError("category 必须为 all / compute_results / uploaded_data")
    if category != "all":
        queryset = queryset.filter(is_compute_result=category == "compute_results")
    return queryset


def catalog_summary(queryset):
    groups = list(
        queryset.values("is_compute_result", "data_type")
        .annotate(count=Count("id"), sizeBytes=Sum("size_bytes"))
        .order_by("is_compute_result", "data_type")
    )
    counts = {"compute_results": 0, "uploaded_data": 0}
    for group in groups:
        group["category"] = (
            "compute_results" if group.pop("is_compute_result") else "uploaded_data"
        )
        group["dataType"] = group.pop("data_type")
        counts[group["category"]] += group["count"]
    return {
        "scope": "current_project_accessible_resources",
        "total": sum(counts.values()),
        "counts": counts,
        "groups": groups,
        "complete": True,
        "classificationBasis": "平台 isComputeResult 登记标记；uploaded_data 为上传/登记的非计算数据，不证明每项均由用户手动上传。",
    }


def catalog_page(queryset, args, brief):
    offset, limit = args.get("offset", 0), args.get("limit", 50)
    if type(offset) is not int or offset < 0 or type(limit) is not int or limit < 1:
        raise ValidationError("offset 必须为非负整数，limit 必须为正整数")
    total = queryset.count()
    found, items, size = [], [], 0
    # A bounded page protects model context; nextOffset permits the complete list.
    page = (
        queryset.order_by("id")[offset : min(total, offset + limit)]
        if offset < total
        else queryset.none()
    )
    for resource in page.iterator():
        item = brief(resource)
        item_size = len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
        if items and size + item_size > 24000:
            break
        found.append(resource)
        items.append(item)
        size += item_size
    next_offset = offset + len(items)
    more = next_offset < total
    return {
        "items": items,
        "total": total,
        "count": len(items),
        "offset": offset,
        "nextOffset": next_offset if more else None,
        "truncated": more,
        "summary": catalog_summary(queryset),
    }, [(r, {"metadata": item}) for r, item in zip(found, items)]
