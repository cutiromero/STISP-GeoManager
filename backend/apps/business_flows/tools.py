"""Two bounded platform tools; definitions and compute remain server controlled."""

from copy import deepcopy
import uuid

from django.core.exceptions import ValidationError

from apps.agent.policy import require_access
from apps.compute.packages import ComputeError
from .models import BusinessFlowDefinition, BusinessFlowVersion


def execute_business_flow_tool(run, user, name, args):
    require_access(user, "agent", run.model)
    if name == "list_business_flows":
        query = args.get("query", "")
        if not isinstance(query, str) or len(query) > 120:
            raise ValidationError("业务流关键词无效")
        offset, limit = args.get("offset", 0), args.get("limit", 8)
        if (
            type(offset) is not int
            or offset < 0
            or type(limit) is not int
            or not 1 <= limit <= 10
        ):
            raise ValidationError("业务流分页范围无效")
        flows = BusinessFlowDefinition.objects.filter(
            is_active=True, name__icontains=query
        ).select_related("current_version")[offset : offset + limit + 1]
        rows = list(flows)
        items = []
        for flow in rows[:limit]:
            if flow.current_version:
                definition = flow.current_version.definition
                items.append(
                    {
                        "id": flow.pk,
                        "code": flow.code,
                        "name": flow.name,
                        "description": flow.description[:800],
                        "versionId": flow.current_version_id,
                        "version": flow.current_version.version,
                        "inputRequirements": definition["inputRequirements"],
                        "nodes": [
                            {
                                key: node[key]
                                for key in ("id", "title", "kind", "review")
                            }
                            for node in definition["nodes"]
                        ],
                    }
                )
        return {
            "items": items,
            "nextOffset": offset + limit if len(rows) > limit else None,
        }, []
    version_id = args.get("versionId")
    if type(version_id) is not int or version_id < 1:
        raise ValidationError("请使用业务流目录返回的已发布versionId")
    version = (
        BusinessFlowVersion.objects.select_related("flow")
        .filter(
            pk=version_id,
            status="published",
            flow__is_active=True,
            flow__project_tag_id=run.project_tag_id,
        )
        .first()
    )
    if not version:
        raise ComputeError("业务流版本不存在或不在当前项目", 404)
    inputs = args.get("inputs", {})
    parameters = deepcopy(args.get("parameters", {}))
    if (
        not isinstance(inputs, dict)
        or not isinstance(parameters, dict)
        or any(type(value) is not int or value < 1 for value in inputs.values())
    ):
        raise ValidationError("业务流资料绑定或参数格式无效")
    if run.data_selection_mode == "manual" and not set(inputs.values()) <= set(
        run.resource_ids
    ):
        raise ValidationError("业务流资料超出了本轮手动选择范围")
    if run.algorithm_selection_mode == "manual":
        versions = {
            node["algorithmVersionId"]
            for node in version.definition["nodes"]
            if node.get("algorithmVersionId")
        }
        if version.definition["adapter"] == "geology_generic" or not versions <= set(
            run.algorithm_version_ids
        ):
            raise ValidationError(
                "业务流需要完整登记的算子组合，请从业务流入口核对后启动"
            )
    if version.definition["adapter"] == "geology_generic" and not parameters.get(
        "uploadBatchId"
    ):
        from apps.agent.workflow_uploads import add_catalog_references

        from apps.agent.models import AgentWorkflow

        existing = AgentWorkflow.objects.filter(
            owner=user,
            project_tag_id=run.project_tag_id,
            idempotency_key=f"business-tool-{run.pk}-{version.pk}",
        ).first()
        if (
            existing
            and existing.parameters.get("_businessFlow", {}).get("versionId")
            == version.pk
        ):
            parameters["uploadBatchId"] = existing.policy_snapshot.get(
                "request", {}
            ).get("uploadBatchId")
        else:
            parameters["uploadBatchId"] = uuid.uuid4().hex
        if not existing:
            add_catalog_references(
                user,
                run.project_tag_id,
                parameters["uploadBatchId"],
                list(inputs.values()),
            )
    from .runtime import start_flow

    workflow = start_flow(
        user,
        version,
        {
            "versionId": version.pk,
            "model": run.model,
            "goal": args.get("goal") or run.prompt,
            "inputs": inputs,
            "parameters": parameters,
            "reviewerModel": args.get("reviewerModel") or run.model,
            "conversationId": run.conversation_id,
            "idempotencyKey": f"business-tool-{run.pk}-{version.pk}",
        },
        source_run=run,
    )
    return {
        "workflowId": str(workflow.pk),
        "flowId": version.flow_id,
        "versionId": version.pk,
        "name": version.flow.name,
        "status": workflow.status,
        "message": "业务流已启动；后续执行、独立审核与人工决定由真实节点控制。",
    }, []
