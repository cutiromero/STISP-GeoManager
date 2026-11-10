"""Publication and discovery of project-scoped, immutable flow definitions."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import F
from django.utils.dateparse import parse_datetime

from apps.compute.models import AlgorithmVersion
from apps.projects.context import (
    is_superadmin,
    require_live_membership,
    selected_project_id,
)
from .definitions import CODE_PATTERN, definition_hash, normalize_definition, text
from .models import BusinessFlowDefinition, BusinessFlowVersion


def require_manager(user):
    require_live_membership()
    if not is_superadmin(user):
        raise PermissionDenied("只有超级管理员可以登记或发布业务流")


def validate_bindings(spec, project_id):
    from .input_policy import for_definition
    from .script_bridges import choose_bridge, versions as script_versions

    script_policy = for_definition(spec)
    bridge_options = None

    def can_prepare(kinds, target):
        nonlocal bridge_options
        if not script_policy["allowScripts"]:
            return False
        if bridge_options is None:
            bridge_options = script_versions()
        return (
            choose_bridge(None, kinds, [target], available=bridge_options) is not None
        )

    identities = {
        node["algorithmVersionId"]
        for node in spec["nodes"]
        if node.get("algorithmVersionId")
    }
    if not identities:
        return
    from apps.compute.services import allowed_algorithms

    rows = AlgorithmVersion.objects.filter(
        pk__in=identities,
        status="published",
        algorithm__enabled=True,
        algorithm__in=allowed_algorithms(),
        algorithm__project_tag_id__in={1, project_id},
    )
    from apps.compute.services import agent_algorithm_allowed

    versions = {
        item.pk: item
        for item in rows.select_related("algorithm")
        if agent_algorithm_allowed(item)
    }
    if set(versions) != identities:
        raise ValidationError(
            "算子绑定必须是当前项目或公开项目允许智能体调用的已发布版本"
        )
    nodes = {node["id"]: node for node in spec["nodes"]}
    roles = {item["key"]: item for item in spec["inputRequirements"]}
    for node in spec["nodes"]:
        bindings = node.get("inputBindings", {})
        if not bindings:
            continue
        manifest = versions[node["algorithmVersionId"]].manifest
        inputs = {item["key"]: item for item in manifest.get("inputs", [])}
        if set(bindings) - set(inputs):
            raise ValidationError("输入连线包含当前已发布算子未声明的输入键")
        for key, source in bindings.items():
            required_kind = inputs[key]["kind"]
            if "role" in source:
                if required_kind not in roles[source["role"]][
                    "dataTypes"
                ] and not can_prepare(
                    roles[source["role"]]["dataTypes"], required_kind
                ):
                    raise ValidationError("绑定资料角色的类型与算子输入不兼容：" + key)
                continue
            upstream = nodes[source["nodeId"]]
            if upstream.get("contract"):
                output = next(
                    (
                        row
                        for row in upstream["contract"]["requiredOutputs"]
                        if row["name"] == source["outputKey"]
                    ),
                    None,
                )
                if output is None or output["semanticType"] == "analysis":
                    raise ValidationError(
                        "前序合同未声明可供计算使用的真实输出：" + source["outputKey"]
                    )
                from .definitions import DATA_TYPES

                if (
                    output["semanticType"] in DATA_TYPES
                    and output["semanticType"] != required_kind
                    and not can_prepare([output["semanticType"]], required_kind)
                ):
                    raise ValidationError("合同声明的成果类型与下游输入不兼容")
                continue
            upstream_manifest = versions[upstream["algorithmVersionId"]].manifest
            outputs = {
                item["key"]: item for item in upstream_manifest.get("outputs", [])
            }
            output = outputs.get(source["outputKey"])
            if output is None:
                raise ValidationError(
                    "前序已发布算子不存在声明的输出键：" + source["outputKey"]
                )
            source_kind = (
                "document"
                if output["kind"] in {"archive", "report"}
                else output["kind"]
            )
            if source_kind != required_kind and not can_prepare(
                [source_kind], required_kind
            ):
                raise ValidationError(
                    "前序输出不能作为当前算子输入：类型不兼容或属于归档文件"
                )

    by_id = versions
    for node in spec["nodes"]:
        version = by_id.get(node.get("algorithmVersionId"))
        if version and set(node.get("parameters", {})) - {
            item["key"] for item in version.manifest["parameters"]
        }:
            raise ValidationError("默认参数包含登记算子版本未声明的字段")


def serialize_flow(flow):
    return {
        "id": flow.pk,
        "projectId": flow.project_tag_id,
        "ownerId": flow.owner_id,
        "code": flow.code,
        "name": flow.name,
        "description": flow.description,
        "isActive": flow.is_active,
        "currentVersionId": flow.current_version_id,
        "createdAt": flow.created_at.isoformat(),
        "updatedAt": flow.updated_at.isoformat(),
    }


def serialize_version(version):
    return {
        "id": version.pk,
        "flowId": version.flow_id,
        "version": version.version,
        "status": version.status,
        "definition": version.definition,
        "createdAt": version.created_at.isoformat(),
        "publishedAt": version.published_at.isoformat(),
    }


def serialize_summary(flow):
    version = flow.current_version
    spec = version.definition if version else {}
    nodes = spec.get("nodes", [])
    return {
        **serialize_flow(flow),
        "version": version.version if version else None,
        "nodeCount": len(nodes),
        "aiReviewCount": sum(bool(node.get("review", {}).get("ai")) for node in nodes),
        "humanReviewCount": sum(
            bool(node.get("review", {}).get("human")) for node in nodes
        ),
        "inputCount": len(spec.get("inputRequirements", [])),
    }


def _locked(flow_id):
    if connection.vendor == "sqlite":
        BusinessFlowDefinition.objects.filter(pk=flow_id).update(
            updated_at=F("updated_at")
        )
    return BusinessFlowDefinition.objects.select_for_update().get(pk=flow_id)


def check_revision(flow, expected):
    if not isinstance(expected, str) or parse_datetime(expected) != flow.updated_at:
        from apps.compute.packages import ComputeError

        raise ComputeError("业务流已由其他页面更新，请刷新后再保存", 409)


def publish_version(user, flow, definition, *, expected=None):
    require_manager(user)
    spec = normalize_definition(definition)
    validate_bindings(spec, flow.project_tag_id)
    with transaction.atomic():
        flow = _locked(flow.pk)
        if expected is not None:
            check_revision(flow, expected)
        number = (
            flow.versions.order_by("-version").values_list("version", flat=True).first()
            or 0
        ) + 1
        version = BusinessFlowVersion.objects.create(
            flow=flow,
            version=number,
            definition=spec,
            definition_hash=definition_hash(spec),
            created_by=user,
        )
        flow.current_version = version
        flow.save(update_fields=["current_version", "updated_at"])
    return flow, version


def register_flow(user, value):
    require_manager(user)
    code = text(value.get("code"), "业务流编码", 80)
    if not CODE_PATTERN.fullmatch(code):
        raise ValidationError(
            "编码以小写英文字母开头，仅包含小写字母、数字、下划线和短横线，长度2至80"
        )
    name = text(value.get("name"), "业务流名称", 120)
    description = text(value.get("description", ""), "业务流说明", 3000, empty=True)
    active = value.get("isActive", True)
    if type(active) is not bool:
        raise ValidationError("启用标记必须是布尔值")
    spec = normalize_definition(value.get("definition"))
    project_id = selected_project_id()
    validate_bindings(spec, project_id)
    with transaction.atomic():
        flow = BusinessFlowDefinition.objects.create(
            project_tag_id=project_id,
            owner=user,
            code=code,
            name=name,
            description=description,
            is_active=active,
        )
        version = BusinessFlowVersion.objects.create(
            flow=flow,
            version=1,
            definition=spec,
            definition_hash=definition_hash(spec),
            created_by=user,
        )
        flow.current_version = version
        flow.save(update_fields=["current_version", "updated_at"])
    return flow, version


def update_flow(user, flow, value):
    require_manager(user)
    with transaction.atomic():
        flow = _locked(flow.pk)
        check_revision(flow, value.get("updatedAt"))
        if "name" in value:
            flow.name = text(value["name"], "业务流名称", 120)
        if "description" in value:
            flow.description = text(
                value["description"], "业务流说明", 3000, empty=True
            )
        if "isActive" in value:
            if type(value["isActive"]) is not bool:
                raise ValidationError("启用标记必须是布尔值")
            flow.is_active = value["isActive"]
        flow.save(update_fields=["name", "description", "is_active", "updated_at"])
    return flow
