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
        queryset = queryset.filter(_agent_compute_result=category == "compute_results")
    return queryset


def catalog_summary(queryset):
    groups = list(
        queryset.values("_agent_compute_result", "data_type")
        .annotate(count=Count("id"), sizeBytes=Sum("size_bytes"))
        .order_by("_agent_compute_result", "data_type")
    )
    counts = {"compute_results": 0, "uploaded_data": 0}
    for group in groups:
        group["category"] = (
            "compute_results" if group.pop("_agent_compute_result") else "uploaded_data"
        )
        group["dataType"] = group.pop("data_type")
        counts[group["category"]] += group["count"]
    return {
        "scope": "current_project_accessible_resources",
        "total": sum(counts.values()),
        "counts": counts,
        "groups": groups,
        "complete": True,
        "classificationBasis": "计算成果须有真实成功任务入库或已完成工作流的终端成果绑定；上传/登记数据包括历史业务登记资料。",
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


def catalog_presentation(queryset, brief):
    """Render verified names once instead of asking an LLM to recopy the list."""
    groups = {True: [], False: []}
    pairs, total_bytes = [], 0
    types = {
        "table": "表格",
        "vector": "矢量",
        "raster": "栅格",
        "document": "文档",
        "image": "图片",
        "gene": "基因",
    }

    def cell(value):
        return (
            str(value)
            .replace("\\", "\\\\")
            .replace("|", "\\|")
            .replace("\n", " ")
            .replace("\r", " ")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("`", "\\`")
            .replace("[", "\\[")
            .replace("]", "\\]")
            .replace("*", "\\*")
            .replace("_", "\\_")
        )

    for resource in queryset.order_by("id").iterator():
        row = f"| {cell(resource.name)} | {types.get(resource.data_type, cell(resource.data_type))} |"
        total_bytes += len(row.encode("utf-8"))
        if total_bytes > 1024 * 1024:
            raise ValidationError(
                "目录超过单次对话展示容量，请按query或category分组查看；总数可用全量统计工具查询"
            )
        groups[resource._agent_compute_result].append(row)
        metadata = brief(resource)
        metadata.pop("description", None)
        pairs.append((resource, {"metadata": metadata}))
    counts = {"compute_results": len(groups[True]), "uploaded_data": len(groups[False])}
    summary = {"total": len(pairs), "counts": counts, "complete": True}
    sections = [
        f"当前授权范围共 **{summary['total']} 项**资源，计算成果 **{counts['compute_results']} 项**，上传/登记数据 **{counts['uploaded_data']} 项**。"
    ]
    for computed, title in ((True, "计算成果"), (False, "上传/登记数据")):
        sections.append(
            f"### {title}（{len(groups[computed])}项）\n\n"
            + (
                "| 名称 | 类型 |\n|---|---|\n" + "\n".join(groups[computed])
                if groups[computed]
                else "暂无。"
            )
        )
    sections.append(
        "计算成果已核对真实入库或终端成果绑定；上传/登记数据包括历史业务登记资料。以上清单由当前授权业务目录直接生成。"
    )
    return {"summary": summary, "answer": "\n\n".join(sections)}, [
        (None, summary),
        *pairs,
    ]
