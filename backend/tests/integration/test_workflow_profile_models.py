"""Profile inference uses the selected thinking mode, budget and live authority."""

import json
import uuid

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied

from apps.agent import context, generic_mapping, provider, workflow_roles
from apps.agent.business_flow_context import ContextReviewRequired
from apps.agent.models import (
    AgentPolicy,
    AgentRun,
    AgentWorkflow,
    Conversation,
    WorkflowUpload,
)
from apps.agent.policy import default_policy
from apps.catalog.models import DataResource
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import ProjectMembership
from tests.integration.test_compute import setup_compute  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def profiles(setup_compute, settings, monkeypatch):  # noqa: F811
    env = setup_compute
    settings.AGENT_MODELS = [
        {
            "alias": "qwen",
            "name": "profile model",
            "model_id": "qwen-profile",
            "base_url": "http://127.0.0.1:19100/v1",
            "agent": True,
            "qwen": True,
        }
    ]
    env["owner"].user_permissions.add(
        *Permission.objects.filter(
            codename__in=["use_local_model", "use_data_agent", "query_data"]
        )
    )
    policy = {
        **default_policy(),
        "operatorEnabled": True,
        "reasoningEffort": "xhigh",
        "maxOutputTokens": 512,
        "maxContextTokens": 2048,
        "maxContextBytes": 64000,
        "maxRunSeconds": 60,
    }
    AgentPolicy.objects.create(value=policy)
    with project_scope(
        ProjectScope((env["project"].id,), env["project"].id, env["owner"].id)
    ):
        resource = DataResource.objects.create(
            name="地质资料",
            code="profile-upload",
            data_type="vector",
            maintainer=env["owner"],
            owner_only=True,
            source="workflow-upload:" + uuid.uuid4().hex,
        )
        upload = WorkflowUpload.objects.create(
            owner=env["owner"],
            batch_id=resource.source.split(":")[1],
            resource=resource,
            file_name="地质图.gpkg",
            profile={
                "kind": "vector",
                "featureCount": 4,
                "geometryTypes": ["Polygon"],
                "crs": "EPSG:32646",
                "fields": [{"name": "DCMC", "type": "text", "samples": ["八宝山组"]}],
            },
        )
        mapping_batch = uuid.uuid4().hex
        mapping_resource = DataResource.objects.create(
            name="待确认字段的地质资料",
            code="profile-mapping-upload",
            data_type="vector",
            maintainer=env["owner"],
            owner_only=True,
            source="workflow-upload:" + mapping_batch,
        )
        workflow = AgentWorkflow.objects.create(
            owner=env["owner"],
            workflow_type="geology_generic",
            model="qwen",
            goal="检查地质资料",
            resource_ids=[mapping_resource.id],
            idempotency_key="profiles",
            plan={
                "uploadInputs": {"lithology": mapping_resource.id},
                "uploadBatchId": mapping_batch,
            },
        )
        WorkflowUpload.objects.create(
            owner=env["owner"],
            batch_id=mapping_batch,
            resource=mapping_resource,
            workflow=workflow,
            file_name="地质字段图.gpkg",
            profile=upload.profile,
        )
        roles = [
            {
                "role": "lithology",
                "resourceId": mapping_resource.id,
                "label": "地质图",
                "fields": ["DCMC"],
                "_profile": upload.profile,
                "targets": [{"key": "name", "label": "地层名称", "required": True}],
            }
        ]
        counted, requests = [], []

        def count_tokens(model, messages, thinking, effort):
            counted.append((thinking, effort))
            return 100

        def stream(model, messages, maximum, guard, **options):
            guard()
            requests.append((maximum, options))
            if "roles" in json.loads(
                messages[1]["content"]
            ) and "items" not in json.loads(messages[1]["content"]):
                yield json.dumps(
                    {
                        "roles": {
                            "lithology": {
                                "name": {"field": "DCMC", "reason": "地层名称示例"}
                            }
                        }
                    }
                )
            else:
                yield json.dumps(
                    {
                        "items": [
                            {
                                "uploadId": json.loads(messages[1]["content"])["items"][
                                    0
                                ]["uploadId"],
                                "role": "lithology",
                                "reason": "矢量面地质资料",
                            }
                        ]
                    }
                )

        monkeypatch.setattr(context, "count_tokens", count_tokens)
        monkeypatch.setattr(provider, "model_window", lambda model: 8192)
        monkeypatch.setattr(provider, "stream", stream)
        yield {
            **env,
            "policy": policy,
            "upload": upload,
            "workflow": workflow,
            "roles": roles,
            "counted": counted,
            "requests": requests,
        }


def infer_roles(env, **options):
    return workflow_roles.recognize_roles(
        env["owner"], env["project"].id, env["upload"].batch_id, "qwen", **options
    )


@pytest.mark.parametrize("thinking", [True, False])
def test_profile_calls_count_and_generate_with_identical_thinking(profiles, thinking):
    profiles["policy"]["thinkingEnabled"] = thinking
    AgentPolicy.objects.update(value=profiles["policy"])
    assert (
        generic_mapping.model_targets(
            profiles["workflow"], profiles["policy"], profiles["roles"]
        )["lithology"]["name"]["field"]
        == "DCMC"
    )
    assert infer_roles(profiles)["source"] == "model"
    assert profiles["counted"] == [(thinking, "xhigh"), (thinking, "xhigh")]
    for index, (maximum, options) in enumerate(profiles["requests"]):
        assert maximum == 512
        assert options["thinking"] is thinking
        assert options["reasoning_effort"] == "xhigh"


def test_field_mapping_keeps_the_callers_smaller_output_budget(profiles):
    generic_mapping.model_targets(
        profiles["workflow"],
        {**profiles["policy"], "maxOutputTokens": 128},
        profiles["roles"],
    )
    assert profiles["requests"][0][0] == 128


def test_role_reference_repair_keeps_original_inputs_and_thinking_setting(
    profiles, monkeypatch
):
    calls = []
    thinking = []

    def stream(model, messages, maximum, guard, **options):
        guard()
        payload = json.loads(messages[1]["content"])
        assert payload["items"][0]["uploadId"] == "file_1"
        assert payload["previousRoles"] == {"lithology": "file_1"}
        calls.append(options["thinking"])
        if len(calls) == 1:
            options["on_thinking"]("矢量面和地层字段符合地质图角色")
        yield json.dumps(
            {
                "items": [
                    {
                        "uploadId": "wrong-reference" if len(calls) == 1 else "file_1",
                        "role": "lithology",
                        "reason": "矢量面包含地层字段",
                    }
                ]
            }
        )

    monkeypatch.setattr(provider, "stream", stream)
    value = infer_roles(
        profiles,
        previous_roles={"lithology": profiles["upload"].resource_id},
        on_thinking=thinking.append,
    )
    assert value["source"] == "model" and value["items"][0]["uploadId"] == str(
        profiles["upload"].id
    )
    assert calls == [True, True] and thinking


@pytest.mark.parametrize("target", ["mapping", "roles"])
def test_over_budget_profiles_never_reach_generation(profiles, monkeypatch, target):
    monkeypatch.setattr(context, "count_tokens", lambda *args: 8000)
    if target == "mapping":
        with pytest.raises(ContextReviewRequired) as waiting:
            generic_mapping.model_targets(
                profiles["workflow"], profiles["policy"], profiles["roles"]
            )
        assert (
            waiting.value.details["afterTokens"]
            > waiting.value.details["inputBudgetTokens"]
        )
    else:
        assert infer_roles(profiles)["source"] == "rules"
    assert not profiles["requests"]


@pytest.mark.parametrize("target", ["mapping", "roles"])
def test_permission_revocation_during_stream_does_not_fall_back(
    profiles, monkeypatch, target
):
    def revoked(model, messages, maximum, guard, **options):
        ProjectMembership.objects.filter(
            project=profiles["project"], user=profiles["owner"]
        ).delete()
        guard()
        yield "{}"

    monkeypatch.setattr(provider, "stream", revoked)
    with pytest.raises(PermissionDenied, match="项目"):
        if target == "mapping":
            generic_mapping.model_targets(
                profiles["workflow"], profiles["policy"], profiles["roles"]
            )
        else:
            infer_roles(profiles)


def test_field_mapping_stops_after_workflow_cancellation(profiles, monkeypatch):
    def cancelled(model, messages, maximum, guard, **options):
        AgentWorkflow.objects.filter(pk=profiles["workflow"].pk).update(
            cancel_requested=True
        )
        guard()
        yield "{}"

    monkeypatch.setattr(provider, "stream", cancelled)
    with pytest.raises(PermissionDenied, match="停止"):
        generic_mapping.model_targets(
            profiles["workflow"], profiles["policy"], profiles["roles"]
        )


def test_role_inference_stops_after_batch_is_bound(profiles, monkeypatch):
    def bound(model, messages, maximum, guard, **options):
        WorkflowUpload.objects.filter(pk=profiles["upload"].pk).update(
            workflow=profiles["workflow"]
        )
        guard()
        yield "{}"

    monkeypatch.setattr(provider, "stream", bound)
    with pytest.raises(PermissionDenied, match="用于任务"):
        infer_roles(profiles)


@pytest.mark.parametrize(
    "mode,effort,thinking", [("fast", "low", False), ("deep", "medium", True)]
)
def test_role_inference_uses_bounded_thinking_with_authorized_source(
    profiles, mode, effort, thinking
):
    conversation = Conversation.objects.create(owner=profiles["owner"], mode="agent")
    run = AgentRun.objects.create(
        owner=profiles["owner"],
        conversation=conversation,
        model="qwen",
        prompt="检查资料",
        thinking_mode=mode,
        reasoning_effort=effort,
        idempotency_key="role-source",
    )
    assert infer_roles(profiles, source_run=run)["source"] == "model"
    assert profiles["counted"] == [(thinking, effort)]
    assert profiles["requests"][0][1]["thinking"] is thinking
    assert profiles["requests"][0][1]["reasoning_effort"] == effort


@pytest.mark.parametrize("effort", ["low", "medium", "xhigh"])
def test_role_preparation_inherits_launch_setting(profiles, effort):
    assert infer_roles(profiles, reasoning_effort=effort)["source"] == "model"
    assert profiles["counted"] == [(True, effort)]
    assert profiles["requests"][0][1]["thinking"] is True
    assert profiles["requests"][0][1]["reasoning_effort"] == effort


@pytest.mark.parametrize("effort", [None, [], "high"])
def test_role_endpoint_rejects_invalid_effort(profiles, effort):
    response = profiles["client"].post(
        "/api/agent/workflow-uploads/recognize/",
        json.dumps(
            {
                "batchId": profiles["upload"].batch_id,
                "model": "qwen",
                "reasoningEffort": effort,
            }
        ),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(profiles["project"].pk),
    )
    assert response.status_code == 400
    assert not profiles["requests"]


@pytest.mark.parametrize(
    "mode,effort,thinking", [("fast", "low", False), ("deep", "medium", True)]
)
def test_field_mapping_inherits_the_bound_source_run(profiles, mode, effort, thinking):
    conversation = Conversation.objects.create(owner=profiles["owner"], mode="agent")
    run = AgentRun.objects.create(
        owner=profiles["owner"],
        conversation=conversation,
        model="qwen",
        prompt="检查资料",
        thinking_mode=mode,
        reasoning_effort=effort,
        idempotency_key="mapping-source",
        research_workflow=profiles["workflow"],
    )
    workflow = profiles["workflow"]
    workflow.plan["chatExecution"] = {"originRunId": run.id, "requestRunId": run.id}
    workflow.save(update_fields=["plan"])
    generic_mapping.model_targets(workflow, profiles["policy"], profiles["roles"])
    assert profiles["counted"] == [(thinking, effort)]
    assert profiles["requests"][0][1]["thinking"] is thinking
    assert profiles["requests"][0][1]["reasoning_effort"] == effort


def test_role_inference_stops_when_the_source_run_is_cancelled(profiles, monkeypatch):
    conversation = Conversation.objects.create(owner=profiles["owner"], mode="agent")
    run = AgentRun.objects.create(
        owner=profiles["owner"],
        conversation=conversation,
        model="qwen",
        prompt="检查资料",
        thinking_mode="deep",
        reasoning_effort="xhigh",
        idempotency_key="cancelled-source",
    )

    def cancelled(model, messages, maximum, guard, **options):
        AgentRun.objects.filter(pk=run.pk).update(cancel_requested=True)
        guard()
        yield "{}"

    monkeypatch.setattr(provider, "stream", cancelled)
    with pytest.raises(PermissionDenied, match="停止"):
        infer_roles(profiles, source_run=run)
