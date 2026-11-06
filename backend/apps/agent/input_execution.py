"""A field-confirmation click can explicitly authorize the initial analysis."""

from apps.compute.packages import ComputeError

from .workflow_resources import resolve_workflow_resource


def _binding(workflow, mapping, revisions, automatic=False):
    from .workflow import _state_hash

    return _state_hash(
        {
            "ownerId": workflow.owner_id,
            "workflowId": str(workflow.pk),
            "projectId": workflow.project_tag_id,
            "goal": workflow.goal,
            "model": workflow.model,
            "batch": workflow.plan.get("uploadBatchId"),
            "inputs": workflow.plan.get("uploadInputs", {}),
            "mapping": mapping,
            "sourceRevisions": revisions,
            **({"applyRuleSuggestions": True} if automatic else {}),
        }
    )


def bind_input_execution(
    workflow, user, policy, mapping, plan_hash, *, automatic=False
):
    from .workflow import _state_hash

    revisions = {
        str(identity): resolve_workflow_resource(
            user, policy, identity, workflow
        ).updated_at.isoformat()
        for identity in workflow.plan["uploadInputs"].values()
    }
    return {
        "planHash": plan_hash,
        "mappingHash": _state_hash(mapping),
        "sourceRevisions": revisions,
        "bindingHash": _binding(workflow, mapping, revisions, automatic),
        **({"applyRuleSuggestions": True} if automatic else {}),
    }


def input_execution_authorized(workflow, user, policy):
    from .workflow import _state_hash

    authorization = workflow.plan.get("inputExecutionAuthorization")
    if authorization is None:
        return False
    if not isinstance(authorization, dict) or not isinstance(
        authorization.get("sourceRevisions"), dict
    ):
        raise ComputeError("资料确认时的分析启动授权无效，请重新核对", 409)
    mapping = workflow.plan.get("confirmedMapping", {})
    revisions = authorization.get("sourceRevisions", {})
    automatic = authorization.get("applyRuleSuggestions", False)
    if (
        type(automatic) is not bool
        or workflow.workflow_type != "geology_generic"
        or authorization.get("mappingHash") != _state_hash(mapping)
        or authorization.get("bindingHash")
        != _binding(workflow, mapping, revisions, automatic)
        or not workflow.steps.filter(
            kind="field_mapping_confirmed",
            status="succeeded",
            output_refs__executionAuthorization=authorization,
        ).exists()
    ):
        raise ComputeError("资料确认时的分析启动授权已变化，请重新核对", 409)
    for identity in workflow.plan["uploadInputs"].values():
        resource = resolve_workflow_resource(user, policy, identity, workflow)
        if revisions.get(str(identity)) != resource.updated_at.isoformat():
            raise ComputeError("资料在确认后已变化，请重新核对后再开始分析", 409)
    return True
