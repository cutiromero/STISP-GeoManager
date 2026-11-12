"""Catalog versions are project-bound, immutable and independent of execution authority."""

from copy import deepcopy
import json
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from apps.business_flows.builtins import (
    GEOLOGY_NODES,
    GEOLOGY_ROLES,
    MINERALS,
    builtin_flows,
    geology_definition,
    source_summary_definition,
)
from apps.business_flows.definitions import normalize_definition
from apps.business_flows.models import BusinessFlowDefinition, BusinessFlowVersion
from apps.projects.models import Project
from tests.integration.test_agent import setup_agent  # noqa: F401

# ruff: noqa: F811


def manager_client(env):
    client = Client()
    client.force_login(env["admin"])
    return client


def create(client, env, **extra):
    return client.post(
        "/api/business-flows/",
        json.dumps({**builtin_flows()[1], **extra}),
        content_type="application/json",
        **env["header"],
    )


def test_catalog_requires_project_login_and_management_is_separate(setup_agent):
    env = setup_agent
    assert Client().get("/api/business-flows/").status_code == 401
    assert env["client"].get("/api/business-flows/").status_code == 400
    assert create(env["client"], env).status_code == 403
    client = manager_client(env)
    response = create(client, env)
    assert response.status_code == 201, response.content
    flow = response.json()["flow"]
    assert flow["projectId"] == env["project"].pk
    listing = env["client"].get("/api/business-flows/", **env["header"])
    assert listing.status_code == 200
    assert listing.json()["canManage"] is False
    assert listing.json()["items"][0]["nodeCount"] == 2
    assert listing.json()["items"][0]["aiReviewCount"] == 0
    assert listing.json()["items"][0]["humanReviewCount"] == 0
    assert create(client, env).status_code == 409


def test_flow_versions_publish_new_snapshots_and_require_current_revision(setup_agent):
    env = setup_agent
    client = manager_client(env)
    first = create(client, env).json()
    flow = first["flow"]
    identity = flow["id"]
    changed = deepcopy(first["version"]["definition"])
    changed["nodes"][0]["title"] = "新的资料分析任务"
    response = client.post(
        f"/api/business-flows/{identity}/versions/",
        json.dumps({"definition": changed, "updatedAt": flow["updatedAt"]}),
        content_type="application/json",
        **env["header"],
    )
    assert response.status_code == 201, response.content
    assert response.json()["version"]["version"] == 2
    original = BusinessFlowVersion.objects.get(pk=first["version"]["id"])
    assert original.definition["nodes"][0]["title"] != "新的资料分析任务"
    original.definition = changed
    with pytest.raises(ValidationError):
        original.save()
    stale = client.patch(
        f"/api/business-flows/{identity}/",
        json.dumps({"name": "过期修改", "updatedAt": flow["updatedAt"]}),
        content_type="application/json",
        **env["header"],
    )
    assert stale.status_code == 409
    flow = response.json()["flow"]
    patch_response = client.patch(
        f"/api/business-flows/{identity}/",
        json.dumps({"isActive": False, "updatedAt": flow["updatedAt"]}),
        content_type="application/json",
        **env["header"],
    )
    assert patch_response.status_code == 200
    assert (
        env["client"].get("/api/business-flows/", **env["header"]).json()["items"] == []
    )
    assert len(client.get("/api/business-flows/", **env["header"]).json()["items"]) == 1


def test_catalog_and_versions_do_not_cross_projects(setup_agent):
    env = setup_agent
    client = manager_client(env)
    first = create(client, env).json()
    other = Project.objects.create(name="其他业务项目", code="other-flow-project")
    response = client.get(
        f"/api/business-flows/{first['flow']['id']}/", HTTP_X_PROJECT_ID=str(other.pk)
    )
    assert response.status_code == 404
    public = client.post(
        "/api/business-flows/",
        json.dumps(builtin_flows()[1]),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(other.pk),
    )
    assert public.status_code == 201
    assert public.json()["flow"]["code"] == first["flow"]["code"]
    assert public.json()["flow"]["projectId"] != first["flow"]["projectId"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda spec: spec["nodes"][0].update(script="unsafe.py"),
        lambda spec: spec["nodes"][0].update(dependsOn=["finish"]),
        lambda spec: spec["nodes"][0].update(dependsOn=["missing"]),
        lambda spec: spec["nodes"][0].update(
            review={"ai": True, "human": False, "maxRevisions": 4}
        ),
        lambda spec: spec["nodes"][0].update(parameters={"command": "run"}),
        lambda spec: spec["inputRequirements"][0].update(dataTypes=["unknown"]),
    ],
)
def test_unregistered_code_cycles_and_unbounded_repairs_are_rejected(mutation):
    spec = source_summary_definition()
    mutation(spec)
    with pytest.raises(ValidationError):
        normalize_definition(spec)


def test_logic_definition_cannot_remove_human_decisions_or_rebind_science():
    for identity in ["inputs", "apply"]:
        spec = geology_definition()
        next(node for node in spec["nodes"] if node["id"] == identity)["review"][
            "human"
        ] = False
        with pytest.raises(ValidationError):
            normalize_definition(spec)
    spec = geology_definition()
    spec["nodes"][1]["algorithmVersionId"] = 1
    with pytest.raises(ValidationError):
        normalize_definition(spec)
    spec = geology_definition()
    spec["nodes"][0], spec["nodes"][1] = spec["nodes"][1], spec["nodes"][0]
    with pytest.raises(ValidationError):
        normalize_definition(spec)
    spec = geology_definition()
    spec["nodes"][2]["review"]["ai"] = False
    assert normalize_definition(spec)["nodes"][2]["review"]["human"] is True


def test_logic_inputs_use_one_open_ended_alteration_collection():
    spec = normalize_definition(geology_definition())
    roles = {item["key"]: item for item in spec["inputRequirements"]}
    assert set(roles) == {"lithology", "faults", "coverage", "units", "alterations"}
    assert roles["lithology"]["label"] == "岩性图"
    assert roles["lithology"]["required"] is True
    assert roles["alterations"]["multiple"] is True
    assert roles["alterations"]["semanticType"] == "class_mask_stack_v1"
    assert all(not set(node["dataRoles"]) & set(MINERALS) for node in spec["nodes"])
    assert "alterations" in spec["nodes"][-2]["dataRoles"]


@pytest.mark.parametrize("with_collection", [False, True])
def test_published_mineral_roles_remain_valid_without_rewriting_history(
    with_collection,
):
    spec = geology_definition()
    spec["inputRequirements"] = [
        {
            "key": key,
            "label": "地质图" if key == "lithology" else label,
            "dataTypes": [kind],
            "required": key == "lithology",
            "requiredFields": [],
            **(
                {"multiple": True, "semanticType": "class_mask_stack_v1"}
                if key == "alterations"
                else {}
            ),
        }
        for key, (label, kind) in GEOLOGY_ROLES.items()
        if with_collection or key != "alterations"
    ]
    for node, (_identity, _title, _kind, roles) in zip(spec["nodes"], GEOLOGY_NODES):
        node["dataRoles"] = [
            role for role in roles if with_collection or role != "alterations"
        ]
    normalized = normalize_definition(spec)
    assert normalized["inputRequirements"][0]["label"] == "地质图"
    assert set(MINERALS) <= set(normalized["nodes"][0]["dataRoles"])
    assert spec["nodes"] == normalized["nodes"]


@pytest.mark.efficiency
def test_catalog_reads_metadata_once_without_scanning_sources(setup_agent):
    env = setup_agent
    client = manager_client(env)
    create(client, env)
    with patch(
        "apps.compute.packages.checksum",
        side_effect=AssertionError("catalog must not read files"),
    ):
        with CaptureQueriesContext(connection) as queries:
            response = env["client"].get("/api/business-flows/", **env["header"])
    assert response.status_code == 200
    reads = [
        row
        for row in queries
        if '"business_flows_businessflowdefinition"' in row["sql"]
    ]
    assert len(reads) == 1


def test_builtin_registration_is_explicit_and_idempotent(setup_agent):
    from django.core.management import call_command
    from io import StringIO

    env = setup_agent
    for _ in range(2):
        output = StringIO()
        call_command(
            "register_business_flows",
            project_id=env["project"].pk,
            user_id=env["admin"].pk,
            stdout=output,
        )
        assert len(json.loads(output.getvalue())["items"]) == 3
    assert (
        BusinessFlowDefinition._base_manager.filter(
            project_tag_id=env["project"].pk
        ).count()
        == 3
    )
    assert BusinessFlowVersion.objects.count() == 3


def test_builtin_registration_preserves_custom_version_until_explicit_update(
    setup_agent,
):
    from django.core.management import call_command
    from io import StringIO

    env = setup_agent
    client = manager_client(env)
    first = create(client, env).json()
    custom = deepcopy(first["version"]["definition"])
    custom["nodes"][0]["title"] = "项目定制分析"
    published = client.post(
        f"/api/business-flows/{first['flow']['id']}/versions/",
        json.dumps({"definition": custom, "updatedAt": first["flow"]["updatedAt"]}),
        content_type="application/json",
        **env["header"],
    )
    assert published.status_code == 201, published.content
    options = {"project_id": env["project"].pk, "user_id": env["admin"].pk}
    output = StringIO()
    call_command("register_business_flows", **options, stdout=output)
    item = next(
        row
        for row in json.loads(output.getvalue())["items"]
        if row["code"] == first["flow"]["code"]
    )
    assert item["published"] is False
    assert item["version"] == 2
    current = BusinessFlowDefinition._base_manager.get(
        pk=first["flow"]["id"]
    ).current_version
    assert current.definition["nodes"][0]["title"] == "项目定制分析"
    output = StringIO()
    call_command(
        "register_business_flows", **options, publish_updates=True, stdout=output
    )
    item = next(
        row
        for row in json.loads(output.getvalue())["items"]
        if row["code"] == first["flow"]["code"]
    )
    assert item["published"] is True
    assert item["version"] == 3


@pytest.mark.parametrize(
    "identity", ["inputs", "check", "recheck", "relations", "prospect"]
)
def test_professional_flow_does_not_advertise_unsupported_ai_gates(identity):
    spec = geology_definition()
    next(node for node in spec["nodes"] if node["id"] == identity)["review"]["ai"] = (
        True
    )
    with pytest.raises(ValidationError):
        normalize_definition(spec)


@pytest.mark.parametrize(
    "identity", ["check", "recheck", "relations", "prospect", "finish"]
)
def test_professional_flow_cannot_invent_extra_human_gates(identity):
    spec = geology_definition()
    next(node for node in spec["nodes"] if node["id"] == identity)["review"][
        "human"
    ] = True
    with pytest.raises(ValidationError):
        normalize_definition(spec)


def test_owner_can_reach_cancellation_boundary_after_agent_permission_revocation(
    setup_agent,
):
    from uuid import uuid4
    from django.core.exceptions import PermissionDenied
    from apps.agent.models import AgentWorkflow
    from apps.business_flows.views import own_workflow
    from apps.projects.context import project_scope

    env = setup_agent
    with project_scope(env["scope"]):
        workflow = AgentWorkflow.objects.create(
            owner=env["user"],
            workflow_type="business_flow",
            goal="停止本人流程",
            model="mock",
            status="paused",
            parameters={"_businessFlow": {}},
            idempotency_key=uuid4().hex,
        )
        with patch(
            "apps.agent.policy.require_access", side_effect=PermissionDenied("已撤权")
        ):
            assert (
                own_workflow(env["user"], workflow.pk, allow_cancel=True).pk
                == workflow.pk
            )
            with pytest.raises(PermissionDenied):
                own_workflow(env["user"], workflow.pk)
        from django.http import Http404

        with pytest.raises(Http404):
            own_workflow(env["other"], workflow.pk, allow_cancel=True)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda spec: spec.update(adapter=[]),
        lambda spec: spec["nodes"][0].update(kind={}),
    ],
)
def test_malformed_declarations_return_validation_instead_of_type_error(mutation):
    spec = source_summary_definition()
    mutation(spec)
    with pytest.raises(ValidationError):
        normalize_definition(spec)


def test_cancel_route_returns_safe_state_after_agent_feature_is_revoked(setup_agent):
    from uuid import uuid4
    from apps.agent.models import AgentPolicy
    from apps.agent.policy import default_policy

    env = setup_agent
    spec = source_summary_definition()
    spec["inputRequirements"] = []
    spec["nodes"][0]["dataRoles"] = []
    created = create(manager_client(env), env, definition=spec).json()
    flow_id = created["flow"]["id"]
    started = env["client"].post(
        f"/api/business-flows/{flow_id}/start/",
        json.dumps(
            {
                "goal": "验证本人停止边界",
                "model": "mock",
                "inputs": {},
                "parameters": {},
                "idempotencyKey": uuid4().hex,
            }
        ),
        content_type="application/json",
        **env["header"],
    )
    assert started.status_code == 202, started.content
    identity = started.json()["id"]
    policy = default_policy()
    policy["agentEnabled"] = False
    AgentPolicy.objects.update_or_create(pk=1, defaults={"value": policy})
    stopped = env["client"].post(
        f"/api/business-flows/runs/{identity}/cancel/",
        json.dumps({}),
        content_type="application/json",
        **env["header"],
    )
    assert stopped.status_code == 200, stopped.content
    value = stopped.json()
    assert value["status"] == "cancelled"
    assert not value["events"]
    assert all(not node["outputs"] for node in value["nodes"])
    assert all("answer" not in node["executor"] for node in value["nodes"])
    assert (
        env["client"]
        .get(f"/api/business-flows/runs/{identity}/", **env["header"])
        .status_code
        == 403
    )


@pytest.mark.efficiency
def test_run_history_projects_json_metadata_without_loading_private_state(setup_agent):
    from uuid import uuid4
    from apps.agent.models import AgentWorkflow
    from apps.projects.context import project_scope

    env = setup_agent
    with project_scope(env["scope"]):
        AgentWorkflow.objects.create(
            owner=env["user"],
            workflow_type="business_flow",
            goal="本人任务",
            model="mock",
            status="succeeded",
            idempotency_key=uuid4().hex,
            parameters={
                "_businessFlow": {
                    "flowId": 123,
                    "versionId": 456,
                    "name": "流程摘要",
                    "conversationId": None,
                    "runId": None,
                    "revision": 7,
                    "state": {"private": "DO_NOT_LOAD_STATE_" * 2000},
                }
            },
            plan={"private": "DO_NOT_LOAD_PLAN_" * 2000},
        )
    with CaptureQueriesContext(connection) as queries:
        response = env["client"].get("/api/business-flows/runs/", **env["header"])
    assert response.status_code == 200, response.content
    assert response.json()["items"][0]["revision"] == 7
    assert "DO_NOT_LOAD" not in response.content.decode()
    reads = [
        row["sql"] for row in queries if 'FROM "agent_agentworkflow"' in row["sql"]
    ]
    assert len(reads) == 1
    assert 'AS "flow_id"' in reads[0]
    assert ', "agent_agentworkflow"."parameters",' not in reads[0]
    assert '"agent_agentworkflow"."plan"' not in reads[0]
    assert '"agent_agentworkflow"."evidence"' not in reads[0]


def test_builtin_flows_expose_three_actual_review_configurations():
    declarations = builtin_flows()
    assert [item["code"] for item in declarations] == [
        "geology-logic-reasoning",
        "research-source-summary",
        "research-source-review",
    ]
    geology, summary, reviewed = [
        normalize_definition(item["definition"]) for item in declarations
    ]
    assert all(
        not node["review"]["ai"] and not node["review"]["human"]
        for node in summary["nodes"]
    )
    assert reviewed["nodes"][0]["id"] == "summarize"
    assert reviewed["nodes"][0]["review"] == {
        "ai": True,
        "human": True,
        "maxRevisions": 1,
    }
    assert reviewed["nodes"][1]["review"] == {
        "ai": False,
        "human": False,
        "maxRevisions": 0,
    }
    assert reviewed["nodes"][1]["dependsOn"] == ["summarize"]
    assert reviewed["inputRequirements"] == summary["inputRequirements"]
    assert {node["id"] for node in geology["nodes"] if node["review"]["ai"]} == {
        "apply",
        "finish",
    }
    assert {node["id"] for node in geology["nodes"] if node["review"]["human"]} == {
        "inputs",
        "apply",
    }
    assert all(
        "演示" not in item["name"] and "测试" not in item["name"]
        for item in declarations
    )
    # Each factory returns independent content; enabling review cannot alter the quick summary.
    reviewed["nodes"][0]["review"]["ai"] = False
    assert builtin_flows()[2]["definition"]["nodes"][0]["review"]["ai"] is True
    assert builtin_flows()[1]["definition"]["nodes"][0]["review"]["ai"] is False
