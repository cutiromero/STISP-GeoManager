"""The schema and unit vocabulary of the registered classification archives."""

from django.core.exceptions import PermissionDenied

from apps.compute.packages import ComputeError

ARCHIVE_SOURCE = "logic-test-data:20261119-v5:"
# The verified reference products share UTM 46N, including Dulan's zone edge.
ARCHIVE_EPSG = 32646
ARCHIVE_RESOLUTIONS_M = {"wulong": 29, "nuomuhong": 30, "dulan": 30}
ARCHIVE_FIELDS = {"geo_sym": "display_symbol", "class_id": "geo_sym"}
UNIT_FIELDS = {
    key: key for key in ("code", "name", "category", "age_ma", "group", "favorable")
}


def _registered_archive(resource):
    return (
        resource.inventory_group_id
        and resource.source.startswith(ARCHIVE_SOURCE)
        and resource.source.removeprefix(ARCHIVE_SOURCE) in ARCHIVE_RESOLUTIONS_M
    )


def registered_fields(resource, columns):
    if not _registered_archive(resource):
        return {}
    if not set(ARCHIVE_FIELDS.values()) <= set(columns):
        raise ComputeError("归档岩性图缺少已登记的图面地质符号或分类编号字段")
    return ARCHIVE_FIELDS


def registered_grid(resource):
    if not _registered_archive(resource):
        return {}
    region = resource.source.removeprefix(ARCHIVE_SOURCE)
    return {
        "working_epsg": ARCHIVE_EPSG,
        "grid_resolution_m": ARCHIVE_RESOLUTIONS_M[region],
    }


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


def authorize_unit_vocabulary(workflow, user, policy, vocabulary):
    from .resource_discovery import resolve_discoverable_resource
    from .workflow_resources import resolve_workflow_resource

    identity = vocabulary["resourceId"]
    if identity in workflow.resource_ids:
        book = resolve_workflow_resource(user, policy, identity, workflow)
    else:
        # An older run can have a prepared plan whose resource list omitted its
        # registered vocabulary. Only rebind at that pre-execution checkpoint.
        if (
            workflow.plan.get("phase") != "review_plan"
            or workflow.execute_operators
            or vocabulary.get("fields") != ARCHIVE_FIELDS
        ):
            raise PermissionDenied("本次归档分类使用的填图单元表未绑定")
        original = workflow.plan.get("effectiveInputs", {}).get(
            "lithology", workflow.plan.get("uploadInputs", {}).get("lithology")
        )
        if type(original) is not int:
            raise PermissionDenied("缺少已确认的归档岩性资料")
        lithology = resolve_workflow_resource(user, policy, original, workflow)
        book = resolve_discoverable_resource(user, policy, identity)
        if (
            not _registered_archive(lithology)
            or book.data_type != "table"
            or book.project_tag_id != lithology.project_tag_id
            or book.source != lithology.source
            or book.inventory_group_id != lithology.inventory_group_id
        ):
            raise PermissionDenied("填图单元表不属于已确认岩性资料的同一归档批次")
    if vocabulary["revision"] != book.updated_at.isoformat():
        raise PermissionDenied("本次归档分类使用的填图单元表已变化，请重新核对资料")
