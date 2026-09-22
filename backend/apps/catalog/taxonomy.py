from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from django.db import transaction

from apps.catalog.models import DataResource, DictionaryItem


class TaxonomyError(ValueError):
    pass


@dataclass(frozen=True)
class TaxonomyNodeDefinition:
    code: str
    name: str
    description: str
    sort_order: int
    selectable: bool = True
    children: tuple["TaxonomyNodeDefinition", ...] = ()


DATA_TAXONOMY_VERSION = "2026.09"
DATA_TAXONOMY = (
    TaxonomyNodeDefinition(
        "spatial", "地理数据", "具有已解析地理坐标的矢量、栅格和坐标表格数据。", 10
    ),
    TaxonomyNodeDefinition(
        "non_spatial", "非地理数据", "没有地理坐标的表格、文档、图片及其他资料。", 20
    ),
)
ROOT_CATEGORY_CODES = frozenset(node.code for node in DATA_TAXONOMY)
SAFE_LEGACY_DOMAIN_CATEGORY_MAP = {}


def data_category_queryset():
    return DictionaryItem.objects.filter(
        dict_type=DictionaryItem.DictType.DATA_CATEGORY
    )


def resolve_data_category(code: str, *, selectable: bool = True) -> DictionaryItem:
    normalized = str(code or "").strip()
    if not normalized:
        raise TaxonomyError("请选择数据分类")
    try:
        category = (
            data_category_queryset()
            .select_related("parent")
            .get(code=normalized, is_active=True)
        )
    except DictionaryItem.DoesNotExist as exc:
        raise TaxonomyError("数据分类不存在或已停用") from exc
    if selectable and not category.is_selectable:
        raise TaxonomyError("请选择可挂接的地理/非地理分类")
    return category


def category_path(category: DictionaryItem | None) -> list[DictionaryItem]:
    if category is None:
        return []
    path: list[DictionaryItem] = []
    seen: set[int] = set()
    current: DictionaryItem | None = category
    while current is not None:
        if current.pk is not None and current.pk in seen:
            raise TaxonomyError("数据分类存在循环父子关系")
        if current.pk is not None:
            seen.add(current.pk)
        if current.dict_type != DictionaryItem.DictType.DATA_CATEGORY:
            raise TaxonomyError("资源分类必须属于数据分类字典")
        path.append(current)
        current = current.parent
    path.reverse()
    return path


def serialize_category_path(category: DictionaryItem | None) -> list[dict]:
    return [
        {"id": item.id, "code": item.code, "name": item.name}
        for item in category_path(category)
    ]


def category_codes_for_filter(code: str) -> list[str]:
    category = resolve_data_category(code, selectable=False)
    items = list(
        data_category_queryset().filter(is_active=True).only("id", "code", "parent_id")
    )
    children: dict[int | None, list[DictionaryItem]] = defaultdict(list)
    for item in items:
        children[item.parent_id].append(item)
    result: list[str] = []
    pending = [category]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if current.id in seen:
            continue
        seen.add(current.id)
        result.append(current.code)
        pending.extend(children.get(current.id, []))
    return result


def taxonomy_tree() -> list[dict]:
    items = list(
        data_category_queryset()
        .filter(is_active=True)
        .select_related("parent")
        .order_by("sort_order", "id")
    )
    children: dict[int | None, list[DictionaryItem]] = defaultdict(list)
    for item in items:
        children[item.parent_id].append(item)

    def serialize(item: DictionaryItem, path: list[str]) -> dict:
        current_path = [*path, item.name]
        return {
            "code": item.code,
            "name": item.name,
            "categoryCode": item.code,
            "selectable": item.is_selectable,
            "description": item.description,
            "path": current_path,
            "domainType": None,
            "spatialClass": item.code if item.code in ROOT_CATEGORY_CODES else None,
            "children": [
                serialize(child, current_path) for child in children.get(item.id, [])
            ],
        }

    return [serialize(item, []) for item in children.get(None, [])]


@transaction.atomic
def assign_resource_category(
    resource: DataResource, category_code: str
) -> DictionaryItem:
    category = resolve_data_category(category_code)
    if category.code != resource.spatial_class:
        raise TaxonomyError("分类须与资源实际地理坐标信息一致")
    if resource.category_id != category.id:
        resource.category = category
        resource.save(update_fields=["category", "updated_at"])
    return category


def safe_legacy_category_code(domain_type: str | None) -> str | None:
    return SAFE_LEGACY_DOMAIN_CATEGORY_MAP.get(str(domain_type or "").strip())


def flatten_taxonomy_definitions(
    nodes: Iterable[TaxonomyNodeDefinition] = DATA_TAXONOMY,
) -> list[TaxonomyNodeDefinition]:
    flattened: list[TaxonomyNodeDefinition] = []
    for node in nodes:
        flattened.append(node)
        flattened.extend(flatten_taxonomy_definitions(node.children))
    return flattened
