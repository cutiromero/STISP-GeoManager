"""The schema and unit vocabulary of the registered classification archives."""

from apps.compute.packages import ComputeError

ARCHIVE_SOURCE = "logic-test-data:20261119-v5:"
ARCHIVE_REGIONS = {"wulong", "nuomuhong", "dulan"}
ARCHIVE_FIELDS = {"geo_sym": "display_symbol", "class_id": "geo_sym"}
UNIT_FIELDS = {
    key: key for key in ("code", "name", "category", "age_ma", "group", "favorable")
}


def registered_fields(resource, columns):
    if not (
        resource.inventory_group_id
        and resource.source.startswith(ARCHIVE_SOURCE)
        and resource.source.removeprefix(ARCHIVE_SOURCE) in ARCHIVE_REGIONS
    ):
        return {}
    if not set(ARCHIVE_FIELDS.values()) <= set(columns):
        raise ComputeError("归档岩性图缺少已登记的图面地质符号或分类编号字段")
    return ARCHIVE_FIELDS


def registered_units(user, policy, lithology):
    from .resource_discovery import discover_resources

    matches = list(
        discover_resources(user, policy)
        .filter(
            data_type="table",
            source=lithology.source,
            project_tag_id=lithology.project_tag_id,
            inventory_group_id=lithology.inventory_group_id,
        )
        .order_by("pk")[:2]
    )
    if len(matches) != 1:
        raise ComputeError("无法确定同批归档填图单元表，请选取该岩性图同批的单元表")
    return matches[0]
