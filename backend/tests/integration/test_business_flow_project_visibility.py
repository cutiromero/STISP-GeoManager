"""Project catalog isolation, shared definitions and project-local execution."""

import json
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.test import Client

from apps.agent.models import AgentRun, AgentWorkflow
from apps.business_flows import catalog, engine, runtime
from apps.business_flows.builtins import builtin_flows, source_summary_definition
from apps.business_flows.definitions import definition_hash, normalize_definition
from apps.business_flows.models import BusinessFlowDefinition, BusinessFlowVersion
from apps.business_flows.state import parent_run
from apps.business_flows.tools import execute_business_flow_tool
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import Project
from tests.integration.test_agent import setup_agent  # noqa: F401
from tests.integration.test_business_flow_runtime import execution_stub

# ruff: noqa: F811


def register(env, project_id, code="shared-summary"):
    spec = source_summary_definition()
    spec["nodes"] = spec["nodes"][:1]
    with project_scope(ProjectScope((project_id,), project_id, env["admin"].pk)):
        return catalog.register_flow(
            env["admin"],
            {
                "code": code,
                "name": code,
                "description": "整理本次项目资料",
                "definition": spec,
            },
        )


def admin_client(env):
    client = Client()
    client.force_login(env["admin"])
    return client


def test_public_catalog_is_shared_and_local_customization_is_not_duplicated(
    setup_agent,
):
    env = setup_agent
    public, _ = register(env, 1)
    local, _ = register(env, env["project"].pk, "local-summary")
    client = admin_client(env)
    items = client.get("/api/business-flows/", **env["header"]).json()["items"]
    assert {r["id"] for r in items} == {public.pk, local.pk}
    assert (
        len(
            client.get("/api/business-flows/?q=shared&limit=1", **env["header"]).json()[
                "items"
            ]
        )
        == 1
    )
    override, _ = register(env, env["project"].pk)
    items = client.get("/api/business-flows/", **env["header"]).json()["items"]
    assert {r["id"] for r in items} == {override.pk, local.pk}
    another = Project.objects.create(code="new-flow-project", name="新项目")
    items = client.get(
        "/api/business-flows/", HTTP_X_PROJECT_ID=str(another.pk)
    ).json()["items"]
    assert [r["id"] for r in items] == [public.pk]
    assert (
        client.get(
            f"/api/business-flows/{local.pk}/", HTTP_X_PROJECT_ID=str(another.pk)
        ).status_code
        == 404
    )


def test_shared_definition_is_readonly_outside_its_registration_project(setup_agent):
    env = setup_agent
    public, version = register(env, 1)
    client = admin_client(env)
    detail = client.get(f"/api/business-flows/{public.pk}/", **env["header"])
    assert detail.status_code == 200
    assert detail.json()["canManage"] is False
    for path, payload, method in [
        (
            f"/api/business-flows/{public.pk}/",
            {"name": "跨项目修改", "updatedAt": public.updated_at.isoformat()},
            client.patch,
        ),
        (
            f"/api/business-flows/{public.pk}/versions/",
            {
                "definition": version.definition,
                "updatedAt": public.updated_at.isoformat(),
            },
            client.post,
        ),
    ]:
        response = method(
            path, json.dumps(payload), content_type="application/json", **env["header"]
        )
        assert response.status_code == 404
    public.refresh_from_db()
    assert public.name == "shared-summary"
    assert (
        client.get(f"/api/business-flows/{public.pk}/", HTTP_X_PROJECT_ID="1").json()[
            "canManage"
        ]
        is True
    )


def seed_legacy_geology(env, project):
    spec = normalize_definition(builtin_flows()[0]["definition"])
    with project_scope(ProjectScope((project.pk,), project.pk, env["admin"].pk)):
        flow = BusinessFlowDefinition.objects.create(
            owner=env["admin"], code="geology-logic-reasoning", name="逻辑推理"
        )
        version = BusinessFlowVersion.objects.create(
            flow=flow,
            version=1,
            definition=spec,
            definition_hash=definition_hash(spec),
            created_by=env["admin"],
        )
        flow.current_version = version
        flow.save()
    return flow, version


def test_specialized_geology_is_hidden_in_all_other_project_entry_points(setup_agent):
    env = setup_agent
    project = env["project"]
    project.code = "02"
    project.save(update_fields=["code"])
    geology, _ = seed_legacy_geology(env, project)
    public_project = Project.objects.get(pk=1)
    public_geology, _ = seed_legacy_geology(env, public_project)
    other = Project.objects.create(code="agriculture", name="农业研究")
    duplicate, duplicate_version = seed_legacy_geology(env, other)
    client = admin_client(env)
    own = client.get("/api/business-flows/", **env["header"]).json()["items"]
    assert [r["id"] for r in own] == [geology.pk]
    for selected in [1, other.pk]:
        header = {"HTTP_X_PROJECT_ID": str(selected)}
        assert client.get("/api/business-flows/", **header).json()["items"] == []
        for identity in [geology.pk, public_geology.pk, duplicate.pk]:
            assert (
                client.get(f"/api/business-flows/{identity}/", **header).status_code
                == 404
            )
            for suffix in ["start", "prepare-inputs"]:
                assert (
                    client.post(
                        f"/api/business-flows/{identity}/{suffix}/",
                        "{}",
                        content_type="application/json",
                        **header,
                    ).status_code
                    == 404
                )
    with project_scope(ProjectScope((other.pk,), other.pk, env["admin"].pk)):
        with pytest.raises(PermissionDenied):
            runtime.start_flow(
                env["admin"],
                duplicate_version,
                {"model": "mock", "idempotencyKey": uuid4().hex},
            )
        response = client.post(
            "/api/business-flows/",
            json.dumps(builtin_flows()[0]),
            content_type="application/json",
            HTTP_X_PROJECT_ID=str(other.pk),
        )
        assert response.status_code == 400


def test_shared_flow_runs_with_only_the_current_project_resources(
    setup_agent, monkeypatch
):
    env = setup_agent
    flow, version = register(env, 1)
    calls = []
    monkeypatch.setattr(
        "apps.agent.business_flow_execution.execute_node", execution_stub(calls)
    )
    with project_scope(env["scope"]):
        workflow = runtime.start_flow(
            env["user"],
            version,
            {
                "model": "mock",
                "goal": "整理当前项目资料",
                "inputs": {"source": env["resource"].pk},
                "idempotencyKey": uuid4().hex,
            },
        )
        assert workflow.project_tag_id == env["project"].pk
        assert parent_run(workflow).project_tag_id == env["project"].pk
        assert parent_run(workflow).conversation.project_tag_id == env["project"].pk
        runtime.authorize(env["user"], workflow)
    engine.advance(workflow.pk)
    engine.advance(workflow.pk)
    workflow.refresh_from_db()
    assert workflow.status == "succeeded"
    assert calls[0]["evidence"][0]["result"]["id"] == env["resource"].pk
    with project_scope(env["scope"]):
        assert runtime.serialize_run(env["user"], workflow)["flowId"] == flow.pk
        run = AgentRun.objects.create(
            owner=env["user"],
            conversation=env["conversation"],
            model="mock",
            prompt="业务流目录",
            status="running",
            idempotency_key=uuid4().hex,
        )
        listed, _ = execute_business_flow_tool(
            run, env["user"], "list_business_flows", {}
        )
        assert [r["id"] for r in listed["items"]] == [flow.pk]
        prepared, _ = execute_business_flow_tool(
            run,
            env["user"],
            "prepare_business_flow_inputs",
            {"versionId": version.pk, "inputs": {"source": env["resource"].pk}},
        )
        assert prepared["items"][0]["sourceId"] == env["resource"].pk
    other = Project.objects.create(code="other-tools", name="其他工具项目")
    with project_scope(ProjectScope((other.pk,), other.pk, env["user"].pk)):
        with pytest.raises(PermissionDenied):
            execute_business_flow_tool(run, env["user"], "list_business_flows", {})


def test_shared_flow_deactivation_blocks_live_steps_but_preserves_own_history(
    setup_agent,
):
    env = setup_agent
    flow, version = register(env, 1)
    with project_scope(env["scope"]):
        workflow = runtime.start_flow(
            env["user"],
            version,
            {
                "model": "mock",
                "inputs": {"source": env["resource"].pk},
                "idempotencyKey": uuid4().hex,
            },
        )
        BusinessFlowDefinition._base_manager.filter(pk=flow.pk).update(is_active=False)
        with pytest.raises(PermissionDenied):
            runtime.authorize(env["user"], workflow)
        runtime.authorize(env["user"], workflow, history=True)
        assert (
            AgentWorkflow.objects.get(pk=workflow.pk).project_tag_id
            == env["project"].pk
        )


@pytest.mark.parametrize(
    "project_code,expected", [("02", ["geology-logic-reasoning"]), ("new-project", [])]
)
def test_project_initialization_registers_only_its_specialized_flows(
    setup_agent, project_code, expected
):
    from io import StringIO
    from django.core.management import call_command

    env = setup_agent
    project = env["project"]
    project.code = project_code
    project.save(update_fields=["code"])
    output = StringIO()
    call_command(
        "register_business_flows",
        project_id=project.pk,
        user_id=env["admin"].pk,
        stdout=output,
    )
    assert [row["code"] for row in json.loads(output.getvalue())["items"]] == expected
    assert (
        list(
            BusinessFlowDefinition._base_manager.filter(
                project_tag_id=project.pk
            ).values_list("code", flat=True)
        )
        == expected
    )
