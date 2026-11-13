"""Real durable flow state with stubbed model results and live scoped sources."""

from copy import deepcopy
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
import pytest

from apps.agent.models import AgentRun
from apps.business_flows import catalog, engine, runtime
from apps.business_flows.builtins import source_summary_definition
from apps.business_flows.models import BusinessFlowVersion
from apps.business_flows.state import parent_run, state
from apps.compute.packages import ComputeError
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import ProjectMembership
from tests.integration.test_agent import setup_agent  # noqa: F401

# ruff: noqa: F811


@pytest.fixture
def flows(setup_agent):
    env = setup_agent

    def create(*, ai=False, human=False, revisions=0, one=False):
        definition = source_summary_definition()
        definition["nodes"][0]["review"] = {
            "ai": ai,
            "human": human,
            "maxRevisions": revisions,
        }
        if one:
            definition["nodes"] = definition["nodes"][:1]
        with project_scope(env["scope"]):
            flow, version = catalog.register_flow(
                env["admin"],
                {
                    "code": "flow-" + uuid4().hex[:10],
                    "name": "资料业务流",
                    "description": "真实资料的可追溯整理",
                    "definition": definition,
                },
            )
        return flow, version

    return {**env, "create": create}


def start(env, version, **options):
    value = {
        "model": "mock",
        "goal": "总结实际资料",
        "inputs": {"source": env["resource"].pk},
        "idempotencyKey": uuid4().hex,
        **options,
    }
    with project_scope(env["scope"]):
        workflow = runtime.start_flow(env["user"], version, value)
    return workflow, value


@pytest.mark.parametrize(
    "steps,expected", [(0, 256), (1, 4), (8, 16), (32, 64), (256, 256)]
)
def test_tool_step_limit_zero_keeps_its_unlimited_meaning(flows, steps, expected):
    from apps.agent.models import AgentPolicy
    from apps.agent.policy import default_policy

    AgentPolicy.objects.update_or_create(
        pk=1, defaults={"value": {**default_policy(), "maxSteps": steps}}
    )
    _, version = flows["create"]()
    workflow, _ = start(flows, version)
    assert workflow.max_iterations == expected
    assert AgentPolicy.objects.get(pk=1).value["maxSteps"] == steps


def execution_stub(calls, *, before_return=None):
    def execute(workflow, node, attempt, evidence, **kwargs):
        calls.append(
            {
                "nodeId": node["id"],
                "attempt": attempt,
                "evidence": deepcopy(evidence),
                "feedback": deepcopy(kwargs.get("feedback")),
            }
        )
        kwargs["guard"]()
        audit = {
            "requestId": uuid4().hex,
            "role": "executor",
            "nodeId": node["id"],
            "modelAlias": "mock",
            "status": "requesting",
            "requested": True,
        }
        kwargs["on_record"](audit)
        if before_return:
            before_return(workflow, kwargs, audit)
        return {
            "summary": "实际资料包含year、value和region字段",
            "findings": ["统计依据来自当前绑定资料"],
            "limitations": [],
            "evidenceIds": [row["id"] for row in evidence],
            "audit": {**audit, "status": "completed"},
        }

    return execute


def reviewer_stub(calls, reject_first=False):
    def review(workflow, node, attempt, evidence, **kwargs):
        calls.append({"attempt": attempt, "evidence": deepcopy(evidence)})
        kwargs["guard"]()
        audit = {
            "requestId": uuid4().hex,
            "role": "reviewer",
            "nodeId": node["id"],
            "modelAlias": "mock",
            "status": "requesting",
            "requested": True,
        }
        kwargs["on_record"](audit)
        if reject_first and attempt == 1:
            return {
                "decision": "request_changes",
                "reason": "缺少适用边界",
                "issues": [
                    {
                        "code": "limits",
                        "message": "请补齐资料局限",
                        "evidenceIds": [evidence[0]["id"]],
                    }
                ],
                "repairInstructions": "补齐局限再提交",
                "evidenceIds": [evidence[0]["id"]],
                "humanApprovalRequired": node["review"]["human"],
                "audit": audit,
            }
        return {
            "decision": "accept",
            "reason": "已依据实际证据核查",
            "issues": [],
            "repairInstructions": "",
            "evidenceIds": [row["id"] for row in evidence],
            "humanApprovalRequired": node["review"]["human"],
            "audit": audit,
        }

    return review


def advance(env, workflow):
    engine.advance(workflow.pk)
    workflow.refresh_from_db()
    with project_scope(env["scope"]):
        return runtime.serialize_run(env["user"], workflow)


def test_one_node_without_review_uses_real_queue_sources_and_finishes(
    flows, monkeypatch
):
    env = flows
    flow, version = env["create"](one=True)
    calls = []
    monkeypatch.setattr(
        "apps.agent.business_flow_execution.execute_node", execution_stub(calls)
    )
    workflow, _ = start(env, version)
    with project_scope(env["scope"]):
        assert parent_run(workflow).status == "waiting_compute"
    result = advance(env, workflow)
    assert workflow.status == "queued" and result["nodes"][0]["status"] == "succeeded"
    assert (
        len(calls) == 1
        and calls[0]["evidence"][0]["result"]["id"] == env["resource"].pk
    )
    assert calls[0]["evidence"][0]["result"]["fields"]
    result = advance(env, workflow)
    assert workflow.status == "succeeded"
    with project_scope(env["scope"]):
        assert parent_run(workflow).status == "succeeded"
    assert result["nodes"][0]["reviewer"]["status"] == "not_required"
    assert result["nodes"][0]["human"]["status"] == "not_required"
    assert isinstance(result["nodes"][0]["outputs"], dict)


def test_ai_rejection_revises_same_node_then_still_waits_for_human(flows, monkeypatch):
    env = flows
    _, version = env["create"](ai=True, human=True, revisions=1)
    executions = []
    reviews = []
    monkeypatch.setattr(
        "apps.agent.business_flow_execution.execute_node", execution_stub(executions)
    )
    monkeypatch.setattr(
        "apps.agent.business_flow_review.review_node", reviewer_stub(reviews, True)
    )
    workflow, _ = start(env, version)
    result = advance(env, workflow)
    assert workflow.status == "queued" and result["nodes"][0]["status"] == "pending"
    assert result["nodes"][0]["attempt"] == 1
    result = advance(env, workflow)
    assert workflow.status == "waiting_approval" and result["nodes"][0]["attempt"] == 2
    assert [row["nodeId"] for row in executions] == ["summarize", "summarize"]
    assert executions[1]["feedback"]["repairInstructions"] == "补齐局限再提交"
    assert result["nodes"][0]["reviewer"]["decision"] == "accept"
    assert result["nodes"][0]["human"]["status"] == "pending"
    assert result["nodes"][1]["status"] == "pending"
    engine.advance(workflow.pk)
    workflow.refresh_from_db()
    assert workflow.status == "waiting_approval" and len(executions) == 2
    with project_scope(env["scope"]):
        assert parent_run(workflow).status == "waiting_review"


def waiting_human(env, monkeypatch):
    _, version = env["create"](human=True, revisions=1)
    monkeypatch.setattr(
        "apps.agent.business_flow_execution.execute_node", execution_stub([])
    )
    workflow, _ = start(env, version)
    result = advance(env, workflow)
    assert workflow.status == "waiting_approval"
    return workflow, result


def test_human_decision_has_revision_fence_and_idempotency(flows, monkeypatch):
    env = flows
    workflow, result = waiting_human(env, monkeypatch)
    payload = {
        "nodeId": "summarize",
        "decision": "approve",
        "feedback": "确认当前证据和结论",
        "revision": result["revision"],
        "idempotencyKey": uuid4().hex,
    }
    with project_scope(env["scope"]):
        with pytest.raises(ComputeError) as wrong:
            runtime.decide_flow(env["user"], workflow, {**payload, "revision": 0})
        assert wrong.value.status == 409
        approved = runtime.decide_flow(env["user"], workflow, payload)
        accepted_revision = state(approved)["revision"]
        repeated = runtime.decide_flow(env["user"], workflow, payload)
        assert state(repeated)["revision"] == accepted_revision
        assert state(repeated)["nodes"]["summarize"]["human"]["status"] == "approved"
        with pytest.raises(ComputeError) as conflict:
            runtime.decide_flow(
                env["user"], workflow, {**payload, "feedback": "改用另一意见"}
            )
        assert conflict.value.status == 409
    result = advance(env, workflow)
    assert result["nodes"][1]["status"] == "succeeded"
    advance(env, workflow)
    assert workflow.status == "succeeded"


def test_human_request_changes_preserves_explicit_actor_status(flows, monkeypatch):
    env = flows
    workflow, result = waiting_human(env, monkeypatch)
    with project_scope(env["scope"]):
        current = runtime.decide_flow(
            env["user"],
            workflow,
            {
                "nodeId": "summarize",
                "decision": "request_changes",
                "feedback": "请明确资料缺少空间坐标的限制",
                "revision": result["revision"],
                "idempotencyKey": uuid4().hex,
            },
        )
        dto = runtime.serialize_run(env["user"], current)
    node = dto["nodes"][0]
    assert node["executor"]["status"] == "pending"
    assert node["reviewer"]["status"] == "not_required"
    assert node["human"]["status"] == "pending" and workflow.pk == current.pk


@pytest.mark.parametrize(
    "action,expected", [("pause", "paused"), ("cancel", "cancelled")]
)
def test_late_model_callbacks_cannot_resurrect_user_control(
    flows, monkeypatch, action, expected
):
    env = flows
    _, version = env["create"]()
    calls = []

    def late(workflow, callbacks, audit):
        with project_scope(env["scope"]):
            runtime.control_flow(env["user"], workflow, action)
        callbacks["on_record"]({**audit, "status": "completed"})

    monkeypatch.setattr(
        "apps.agent.business_flow_execution.execute_node",
        execution_stub(calls, before_return=late),
    )
    workflow, _ = start(env, version)
    engine.advance(workflow.pk)
    workflow.refresh_from_db()
    assert workflow.status == expected
    with project_scope(env["scope"]):
        assert parent_run(workflow).status == (
            "cancelled" if action == "cancel" else "waiting_input"
        )
    engine.advance(workflow.pk)
    workflow.refresh_from_db()
    assert workflow.status == expected and len(calls) == 1


def test_start_idempotency_reuses_one_durable_workflow_and_parent_run(flows):
    env = flows
    _, version = env["create"]()
    workflow, payload = start(env, version)
    with project_scope(env["scope"]):
        same = runtime.start_flow(env["user"], version, payload)
        assert same.pk == workflow.pk
        assert AgentRun.objects.filter(research_workflow=workflow).count() == 1
        with pytest.raises(ComputeError) as mismatch:
            runtime.start_flow(env["user"], version, {**payload, "goal": "另一任务"})
        assert mismatch.value.status == 409


def test_owner_project_version_and_resource_revisions_are_live_boundaries(flows):
    env = flows
    _, version = env["create"]()
    workflow, _ = start(env, version)
    with project_scope(env["scope"]), pytest.raises(PermissionDenied):
        runtime.serialize_run(env["other"], workflow)
    with (
        project_scope(ProjectScope((1,), 1, env["user"].pk)),
        pytest.raises(PermissionDenied),
    ):
        runtime.serialize_run(env["user"], workflow)
    with project_scope(env["scope"]):
        frozen = deepcopy(version.definition)
        frozen["outputRequirements"] = ["被篡改版本"]
        BusinessFlowVersion.objects.filter(pk=version.pk).update(definition=frozen)
        with pytest.raises(PermissionDenied):
            runtime.serialize_run(env["user"], workflow)
        BusinessFlowVersion.objects.filter(pk=version.pk).update(
            definition=version.definition
        )
        env["resource"].name = "资料已换版"
        env["resource"].save()
        with pytest.raises(PermissionDenied, match="版本已变化"):
            runtime.serialize_run(env["user"], workflow)


def test_revoked_source_or_membership_never_reaches_execution(flows, monkeypatch):
    env = flows
    _, version = env["create"]()
    workflow, _ = start(env, version)
    calls = []
    monkeypatch.setattr(
        "apps.agent.business_flow_execution.execute_node", execution_stub(calls)
    )
    ProjectMembership.objects.filter(project=env["project"], user=env["user"]).delete()
    engine.advance(workflow.pk)
    workflow.refresh_from_db()
    assert workflow.status == "interrupted" and not calls


def test_live_source_acl_revocation_cannot_be_hidden_by_prepared_metadata(
    flows, monkeypatch
):
    from apps.catalog.models import DataResource

    env = flows
    _, version = env["create"]()
    calls = []
    monkeypatch.setattr(
        "apps.agent.business_flow_execution.execute_node", execution_stub(calls)
    )
    workflow, _ = start(env, version)
    advance(env, workflow)
    with project_scope(env["scope"]):
        DataResource.objects.filter(pk=env["resource"].pk).update(
            owner_only=True, maintainer=env["other"]
        )
    engine.advance(workflow.pk)
    workflow.refresh_from_db()
    assert workflow.status == "interrupted" and len(calls) == 1
    with project_scope(env["scope"]), pytest.raises(PermissionDenied):
        runtime.serialize_run(env["user"], workflow)


def test_paused_owner_can_still_cancel_after_source_version_changes(flows):
    env = flows
    _, version = env["create"]()
    workflow, _ = start(env, version)
    with project_scope(env["scope"]):
        paused = runtime.control_flow(env["user"], workflow, "pause")
        env["resource"].description = "资料版本已变化"
        env["resource"].save()
        stopped = runtime.control_flow(env["user"], paused, "cancel")
    assert stopped.status == "cancelled"
    with project_scope(env["scope"]):
        assert parent_run(stopped).status == "cancelled"


def test_exhausted_ai_revision_does_not_autopass_or_keep_requesting(flows, monkeypatch):
    env = flows
    _, version = env["create"](ai=True, human=True, revisions=0)
    executions = []
    reviews = []
    monkeypatch.setattr(
        "apps.agent.business_flow_execution.execute_node", execution_stub(executions)
    )
    monkeypatch.setattr(
        "apps.agent.business_flow_review.review_node", reviewer_stub(reviews, True)
    )
    workflow, _ = start(env, version)
    advance(env, workflow)
    assert workflow.status == "waiting_approval"
    assert (
        state(workflow)["nodes"]["summarize"]["contextRecovery"]["kind"]
        == "review_rejected"
    )
    assert len(executions) == len(reviews) == 1
    assert state(workflow)["nodes"]["summarize"]["human"]["status"] == "pending"
    engine.advance(workflow.pk)
    workflow.refresh_from_db()
    assert (
        workflow.status == "waiting_approval" and len(executions) == len(reviews) == 1
    )


def test_new_publication_does_not_rewrite_running_version_snapshot(flows):
    env = flows
    flow, version = env["create"]()
    workflow, _ = start(env, version)
    revised = deepcopy(version.definition)
    revised["nodes"][0]["instruction"] = "新版节点规范"
    with project_scope(env["scope"]):
        _, new = catalog.publish_version(
            env["admin"], flow, revised, expected=flow.updated_at.isoformat()
        )
        result = runtime.serialize_run(env["user"], workflow)
    assert new.pk != version.pk
    assert result["versionId"] == version.pk
    assert (
        result["definitionSnapshot"]["nodes"][0]["instruction"]
        == version.definition["nodes"][0]["instruction"]
    )


@pytest.mark.efficiency
def test_source_preparation_is_reused_across_revisions_and_nodes(flows, monkeypatch):
    from apps.catalog import data_query

    env = flows
    _, version = env["create"](ai=True, revisions=1)
    calls = []
    reviews = []
    profiles = []
    original = data_query.get_resource_profile

    def counted(resource):
        profiles.append(resource.pk)
        return original(resource)

    monkeypatch.setattr(data_query, "get_resource_profile", counted)
    monkeypatch.setattr(
        "apps.agent.business_flow_execution.execute_node", execution_stub(calls)
    )
    monkeypatch.setattr(
        "apps.agent.business_flow_review.review_node", reviewer_stub(reviews, True)
    )
    workflow, _ = start(env, version)
    for _ in range(4):
        advance(env, workflow)
    assert workflow.status == "succeeded"
    assert len(calls) == 2 and profiles == [env["resource"].pk]
    assert calls[0]["evidence"][0]["result"]["sample"]
    assert calls[0]["evidence"][0]["result"]["totalRows"] == 4


@pytest.mark.efficiency
def test_multiple_roles_for_one_resource_share_preparation(flows, monkeypatch):
    from apps.catalog import data_query

    env = flows
    definition = source_summary_definition()
    definition["inputRequirements"].append(
        {**definition["inputRequirements"][0], "key": "context", "label": "背景资料"}
    )
    definition["nodes"][0]["dataRoles"] = ["source", "context"]
    with project_scope(env["scope"]):
        _, version = catalog.register_flow(
            env["admin"],
            {
                "code": "same-" + uuid4().hex[:8],
                "name": "同源多角色",
                "definition": definition,
            },
        )
    profiles = []
    original = data_query.get_resource_profile

    def counted(resource):
        profiles.append(resource.pk)
        return original(resource)

    monkeypatch.setattr(data_query, "get_resource_profile", counted)
    monkeypatch.setattr(
        "apps.agent.business_flow_execution.execute_node", execution_stub([])
    )
    workflow, _ = start(
        env,
        version,
        inputs={"source": env["resource"].pk, "context": env["resource"].pk},
    )
    result = advance(env, workflow)
    assert result["nodes"][0]["status"] == "succeeded"
    assert profiles == [env["resource"].pk]


def test_cancel_endpoint_remains_available_when_agent_policy_is_disabled(
    flows, monkeypatch
):
    import json
    from apps.agent.models import AgentPolicy
    from apps.agent.policy import default_policy

    env = flows
    workflow, _ = waiting_human(env, monkeypatch)
    policy = default_policy()
    policy["agentEnabled"] = False
    AgentPolicy.objects.update_or_create(pk=1, defaults={"value": policy})
    response = env["client"].post(
        f"/api/business-flows/runs/{workflow.pk}/cancel/",
        json.dumps({}),
        content_type="application/json",
        **env["header"],
    )
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "cancelled"
    assert all(node["outputs"] == {} for node in response.json()["nodes"])


def test_stop_after_source_revocation_cannot_expose_old_feedback(flows, monkeypatch):
    import json
    from apps.catalog.models import DataResource

    env = flows
    workflow, _ = waiting_human(env, monkeypatch)
    marker = "PRIVATE_PREVIOUS_SOURCE_7cc2"
    state(workflow)["nodes"]["summarize"]["feedback"] = {
        "reason": marker,
        "repairInstructions": marker,
    }
    state(workflow)["nodes"]["summarize"]["human"]["reason"] = marker
    workflow.save(update_fields=["plan"])
    with project_scope(env["scope"]):
        DataResource.objects.filter(pk=env["resource"].pk).update(
            owner_only=True, maintainer=env["other"]
        )
    response = env["client"].post(
        f"/api/business-flows/runs/{workflow.pk}/cancel/",
        json.dumps({}),
        content_type="application/json",
        **env["header"],
    )
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "cancelled"
    assert marker not in response.content.decode()


def test_human_approval_checks_compute_slot_without_losing_pending_decision(
    flows, monkeypatch
):
    env = flows
    waiting, result = waiting_human(env, monkeypatch)
    _, version = env["create"]()
    other, _ = start(env, version)
    with project_scope(env["scope"]):
        with pytest.raises(ComputeError) as busy:
            runtime.decide_flow(
                env["user"],
                waiting,
                {
                    "nodeId": "summarize",
                    "decision": "approve",
                    "feedback": "确认",
                    "revision": result["revision"],
                    "idempotencyKey": uuid4().hex,
                },
            )
        assert busy.value.status == 409
        waiting.refresh_from_db()
        other.refresh_from_db()
        assert (
            waiting.status == "waiting_approval"
            and state(waiting)["nodes"]["summarize"]["human"]["status"] == "pending"
        )
        assert other.status == "queued"


def test_pause_and_resume_preserve_a_pending_human_gate(flows, monkeypatch):
    env = flows
    workflow, _ = waiting_human(env, monkeypatch)
    with project_scope(env["scope"]):
        paused = runtime.control_flow(env["user"], workflow, "pause")
        paused.refresh_from_db()
        assert paused.status == "paused" and paused.pause_requested is True
        assert paused.paused_from == "waiting_approval"
        resumed = runtime.control_flow(env["user"], paused, "resume")
        resumed.refresh_from_db()
        assert resumed.status == "waiting_approval" and not resumed.pause_requested
        assert state(resumed)["nodes"]["summarize"]["human"]["status"] == "pending"
        assert parent_run(resumed).status == "waiting_review"


def test_pause_resume_and_cancel_are_durable_user_intents(flows):
    env = flows
    _, version = env["create"]()
    workflow, _ = start(env, version)
    with project_scope(env["scope"]):
        paused = runtime.control_flow(env["user"], workflow, "pause")
        paused.refresh_from_db()
        assert (
            paused.status == "paused"
            and paused.pause_requested
            and paused.paused_from == "queued"
        )
        resumed = runtime.control_flow(env["user"], paused, "resume")
        resumed.refresh_from_db()
        assert resumed.status == "queued" and not resumed.pause_requested
        stopped = runtime.control_flow(env["user"], resumed, "cancel")
        stopped.refresh_from_db()
        assert stopped.status == "cancelled" and stopped.cancel_requested


def test_pause_resume_epoch_discards_a_late_original_model_result(flows, monkeypatch):
    env = flows
    _, version = env["create"]()
    calls = []

    def switch(workflow, callbacks, audit):
        with project_scope(env["scope"]):
            paused = runtime.control_flow(env["user"], workflow, "pause")
            runtime.control_flow(env["user"], paused, "resume")
        callbacks["on_record"]({**audit, "status": "completed"})

    monkeypatch.setattr(
        "apps.agent.business_flow_execution.execute_node",
        execution_stub(calls, before_return=switch),
    )
    workflow, _ = start(env, version)
    engine.advance(workflow.pk)
    workflow.refresh_from_db()
    assert workflow.status == "queued" and not workflow.cancel_requested
    assert not state(workflow)["nodes"]["summarize"]["executor"].get("summary")
    assert len(calls) == 1
    monkeypatch.setattr(
        "apps.agent.business_flow_execution.execute_node", execution_stub(calls)
    )
    advance(env, workflow)
    assert (
        state(workflow)["nodes"]["summarize"]["status"] == "succeeded"
        and len(calls) == 2
    )


@pytest.mark.efficiency
def test_twenty_bound_resources_use_one_live_acl_resource_query(flows):
    from apps.agent.models import AgentPolicy
    from apps.agent.policy import default_policy

    policy = default_policy()
    policy["maxResources"] = 30
    AgentPolicy.objects.update_or_create(pk=1, defaults={"value": policy})
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from apps.catalog.models import DataResource

    env = flows
    definition = source_summary_definition()
    inputs = {}
    with project_scope(env["scope"]):
        requirements = []
        for index in range(20):
            role = "source" if index == 0 else f"source{index}"
            resource = (
                env["resource"]
                if index == 0
                else DataResource.objects.create(
                    name=f"资料{index}",
                    code="many-" + uuid4().hex,
                    data_type="table",
                    file_format="SQLITE",
                    storage_path="samples",
                )
            )
            requirements.append(
                {
                    **definition["inputRequirements"][0],
                    "key": role,
                    "label": f"资料{index}",
                }
            )
            inputs[role] = resource.pk
        definition["inputRequirements"] = requirements
        definition["nodes"][0]["dataRoles"] = list(inputs)
        _, version = catalog.register_flow(
            env["admin"],
            {
                "code": "many-" + uuid4().hex[:8],
                "name": "多来源",
                "definition": definition,
            },
        )
    workflow, _ = start(env, version, inputs=inputs)
    with project_scope(env["scope"]):
        with CaptureQueriesContext(connection) as queries:
            runtime.authorize(env["user"], workflow)
        assert sum('"catalog_dataresource"' in row["sql"] for row in queries) <= 1
        guard = engine.live_guard(workflow)
        with CaptureQueriesContext(connection) as queries:
            guard()
        assert sum('"catalog_dataresource"' in row["sql"] for row in queries) <= 1


def test_shared_resource_cache_still_validates_each_roles_required_fields(
    flows, monkeypatch
):
    env = flows
    definition = source_summary_definition()
    calls = []
    definition["inputRequirements"].append(
        {
            **definition["inputRequirements"][0],
            "key": "context",
            "label": "背景资料",
            "requiredFields": ["missing_scientific_field"],
        }
    )
    definition["nodes"][0]["dataRoles"] = ["source", "context"]
    with project_scope(env["scope"]):
        _, version = catalog.register_flow(
            env["admin"],
            {
                "code": "field-cache-" + uuid4().hex[:8],
                "name": "共享资料不同约束",
                "definition": definition,
            },
        )
    monkeypatch.setattr(
        "apps.agent.business_flow_execution.execute_node", execution_stub(calls)
    )
    inputs = {"source": env["resource"].pk, "context": env["resource"].pk}
    with project_scope(env["scope"]):
        from apps.agent.policy import require_access

        _, _, planned = runtime._inputs(
            env["user"],
            version.definition,
            {"inputs": inputs},
            require_access(env["user"], "agent", "mock"),
            preview=True,
        )
        assert planned["ready"] is False
        assert {item["role"]: item["status"] for item in planned["items"]} == {
            "source": "direct",
            "context": "unavailable",
        }
    with pytest.raises(ValidationError, match="输入仍需配置"):
        start(env, version, inputs=inputs)
    assert not calls
