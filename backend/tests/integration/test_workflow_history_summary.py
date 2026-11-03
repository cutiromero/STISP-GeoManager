"""History indexes must be small, scene-scoped and independent of heavy results."""

import json
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.agent.models import AgentWorkflow, AgentWorkflowStep
from apps.agent.workflow_history import summary_list
from apps.projects.context import ProjectScope, project_scope
from tests.integration.test_agent import setup_agent  # noqa: F401


def saved(env, key, *, owner=None, scenario="geology_map_review"):
    with project_scope(env["scope"]):
        workflow = AgentWorkflow.objects.create(
            owner=owner or env["user"],
            workflow_type=scenario,
            goal="检查已有地质图" + "目标" * 300,
            model="mock",
            status="succeeded",
            resource_ids=[env["resource"].id],
            idempotency_key=key,
            plan={"largeSavedResult": "x" * 200_000},
            evidence=[{"saved": "x" * 50_000}],
        )
        AgentWorkflowStep.objects.create(
            workflow=workflow,
            sequence=1,
            kind="review",
            status="succeeded",
            action={"largeToolReturn": "x" * 100_000},
        )
    return workflow


def test_summary_filters_owner_project_and_scenario_and_has_pagination(setup_agent):  # noqa: F811
    env = setup_agent
    first = saved(env, "history-first")
    latest = saved(env, "history-latest")
    saved(env, "history-other-scene", scenario="ecology_investigation")
    saved(env, "history-other-user", owner=env["other"])
    with project_scope(ProjectScope((1,), 1, env["user"].id)):
        AgentWorkflow.objects.create(
            owner=env["user"],
            workflow_type="geology_map_review",
            model="mock",
            status="succeeded",
            goal="另一个项目",
            idempotency_key="public-history",
        )
    url = "/api/agent/workflows/?view=summary&workflowType=geology_map_review&limit=1"
    with patch(
        "apps.agent.workflow.authorize_workflow_history",
        side_effect=AssertionError("Heavy authorization called for metadata"),
    ):
        response = env["client"].get(url, **env["header"])
    assert response.status_code == 200, response.content
    data = response.json()
    assert data["total"] == 2 and data["hasMore"] and data["limit"] == 1
    assert data["items"][0]["id"] == str(latest.id)
    assert len(data["items"][0]["goal"]) == 300
    assert (
        not {"plan", "evidence", "steps", "parameters", "resultIds"}
        & data["items"][0].keys()
    )
    assert len(response.content) < 3000
    page = env["client"].get(url + "&offset=1", **env["header"]).json()
    assert page["items"][0]["id"] == str(first.id) and not page["hasMore"]


def test_index_never_selects_large_json_or_step_rows(setup_agent):  # noqa: F811
    env = setup_agent
    for index in range(5):
        saved(env, "history-query-" + str(index))
    with project_scope(env["scope"]), CaptureQueriesContext(connection) as captured:
        result = summary_list(env["user"], {"workflowType": "geology_map_review"})
    assert len(result["items"]) == 5
    assert len(captured) == 2
    queries = " ".join(item["sql"] for item in captured)
    assert '"plan"' not in queries and '"evidence"' not in queries
    assert "agent_agentworkflowstep" not in queries


def test_summary_does_not_leak_to_another_user_or_project(setup_agent):  # noqa: F811
    env = setup_agent
    saved(env, "history-scope")
    with project_scope(
        ProjectScope((env["project"].id,), env["project"].id, env["other"].id)
    ):
        assert summary_list(env["other"], {})["items"] == []
    public = env["client"].get(
        "/api/agent/workflows/?view=summary", HTTP_X_PROJECT_ID="1"
    )
    assert public.status_code == 200 and public.json()["items"] == []


def test_summary_validates_pagination_and_scene_without_running_any_task(setup_agent):  # noqa: F811
    env = setup_agent
    for query in (
        "limit=0",
        "limit=101",
        "offset=-1",
        "offset=no",
        "workflowType=bad/path",
        "view=unknown",
    ):
        response = env["client"].get(
            "/api/agent/workflows/?view=summary&" + query, **env["header"]
        )
        assert response.status_code == 400, (query, response.content)
    assert AgentWorkflow._base_manager.count() == 0


def test_detail_still_applies_original_evidence_authorization(setup_agent):  # noqa: F811
    env = setup_agent
    workflow = saved(env, "history-detail")
    # Loading an index cannot be used as an authorization grant for full results.
    from django.core.exceptions import PermissionDenied

    with patch(
        "apps.agent.workflow.authorize_workflow_history",
        side_effect=PermissionDenied("依据已撤回"),
    ):
        index = env["client"].get("/api/agent/workflows/?view=summary", **env["header"])
        detail = env["client"].get(
            f"/api/agent/workflows/{workflow.id}/", **env["header"]
        )
    assert index.status_code == 200 and len(index.json()["items"]) == 1
    assert detail.status_code == 403
    assert "依据已撤回" in json.loads(detail.content)["detail"]
