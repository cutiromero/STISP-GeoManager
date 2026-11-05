from apps.agent.models import AgentWorkflow
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent as setup_agent


def test_projections_keep_owner_and_project_permissions(setup_agent):
    env = setup_agent
    with project_scope(env["scope"]):
        saved = AgentWorkflow.objects.create(
            owner=env["user"],
            workflow_type="geology_generic",
            model="mock",
            resource_ids=[env["resource"].id],
            idempotency_key="projection-owned",
            plan={"phase": "completed"},
        )
        hidden = AgentWorkflow.objects.create(
            owner=env["other"],
            workflow_type="geology_generic",
            model="mock",
            idempotency_key="projection-hidden",
        )
    for view in ("compare", "inspection"):
        response = env["client"].get(
            f"/api/agent/workflows/{saved.id}/?view={view}", **env["header"]
        )
        assert response.status_code == 200, response.content
        assert response.json()["view"] == view
        assert (
            env["client"]
            .get(f"/api/agent/workflows/{hidden.id}/?view={view}", **env["header"])
            .status_code
            == 404
        )
        assert env["client"].get(
            f"/api/agent/workflows/{saved.id}/?view={view}", HTTP_X_PROJECT_ID="1"
        ).status_code in (403, 404)
        assert (
            env["client"]
            .get(
                f"/api/agent/workflows/{saved.id}/?view={view}&limit=51",
                **env["header"],
            )
            .status_code
            == 400
        )


def test_card_and_inspection_preserve_reused_configuration_and_mapping_card(
    setup_agent,
):
    env = setup_agent
    review = {
        "roles": [],
        "questions": ["确认地层字段"],
        "modelMode": "mock",
        "confirmed": False,
    }
    with project_scope(env["scope"]):
        saved = AgentWorkflow.objects.create(
            owner=env["user"],
            workflow_type="geology_generic",
            model="mock",
            status="waiting_approval",
            resource_ids=[env["resource"].id],
            idempotency_key="projection-mapping",
            plan={
                "phase": "review_mapping",
                "fieldMappingReview": review,
                "reusedConfiguration": True,
            },
        )
    for view in ("card", "inspection"):
        response = env["client"].get(
            f"/api/agent/workflows/{saved.id}/?view={view}", **env["header"]
        )
        assert response.status_code == 200, response.content
        assert response.json()["plan"]["fieldMappingReview"] == review
        assert response.json()["plan"]["reusedConfiguration"] is True
