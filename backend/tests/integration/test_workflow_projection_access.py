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
        assert response.json()["taskSummary"]["initialIssueCount"] is None
        assert response.json()["taskSummary"]["completedCalculations"] == 0


def test_attempt_response_pagination_preserves_full_audit_and_owner_scope(setup_agent):
    from apps.agent.decision_audit import response_artifact

    env = setup_agent
    artifact = response_artifact("完整原始发现" * 2000)
    with project_scope(env["scope"]):
        workflow = AgentWorkflow.objects.create(
            owner=env["user"],
            workflow_type="geology_generic",
            model="mock",
            idempotency_key="attempt-response-owned",
            plan={"phase": "failed"},
        )
        hidden = AgentWorkflow.objects.create(
            owner=env["other"],
            workflow_type="geology_generic",
            model="mock",
            idempotency_key="attempt-response-hidden",
        )
    for item in (workflow, hidden):
        item.steps.create(
            sequence=1,
            kind="analysis_model_attempt",
            status="failed",
            message="decision.findings 第2项应为字符串或对象，实际类型为 int",
            output_refs={"modelResponse": artifact},
        )
    query = "?view=inspection&part=steps&offset=0&limit=1"
    response = env["client"].get(
        f"/api/agent/workflows/{workflow.id}/{query}", **env["header"]
    )
    assert response.status_code == 200, response.content
    audit = response.json()["steps"][0]
    assert audit["outputRefs"]["modelResponse"] == artifact
    assert "findings 第2项" in audit["message"]
    assert (
        env["client"]
        .get(f"/api/agent/workflows/{hidden.id}/{query}", **env["header"])
        .status_code
        == 404
    )
    assert env["client"].get(
        f"/api/agent/workflows/{workflow.id}/{query}", HTTP_X_PROJECT_ID="1"
    ).status_code in (403, 404)


def test_review_steps_do_not_expose_string_decisions_as_analysis(setup_agent):
    env = setup_agent
    decision = {
        "problem": "检查",
        "judgement": "判断",
        "nextAction": "geology-multi-apply",
        "algorithmReason": "依据",
        "findings": [],
        "uncertainties": [],
        "evidenceRefs": [],
    }
    with project_scope(env["scope"]):
        workflow = AgentWorkflow.objects.create(
            owner=env["user"],
            workflow_type="geology_generic",
            model="mock",
            idempotency_key="review-step-decision",
            plan={"phase": "completed"},
        )
    workflow.steps.create(
        sequence=1,
        kind="analysis_decision",
        status="succeeded",
        action={"decision": decision},
    )
    workflow.steps.create(
        sequence=2,
        kind="review_feedback",
        status="succeeded",
        action={"decision": "approve", "feedback": "", "planHash": "x"},
    )
    for query in ("?view=card", "?view=inspection&part=steps&offset=0&limit=25"):
        response = env["client"].get(
            f"/api/agent/workflows/{workflow.id}/{query}", **env["header"]
        )
        assert response.status_code == 200, response.content
        for step in response.json()["steps"]:
            if step["kind"] == "review_feedback":
                assert step["decision"] is None
                assert step["action"]["decision"] == "approve"
            else:
                assert step["decision"]["problem"] == "检查"
    steps = response.json()["steps"]
    assert {step["kind"] for step in steps} == {
        "analysis_decision",
        "review_feedback",
    }


def test_retained_review_endpoint_keeps_owner_and_project_boundary(setup_agent):
    from unittest.mock import patch

    env = setup_agent
    with project_scope(env["scope"]):
        own = AgentWorkflow.objects.create(
            owner=env["user"],
            workflow_type="geology_generic",
            model="mock",
            idempotency_key="held-own",
            status="succeeded",
            plan={"phase": "completed"},
            plan_hash="a" * 64,
        )
        other = AgentWorkflow.objects.create(
            owner=env["other"],
            workflow_type="geology_generic",
            model="mock",
            idempotency_key="held-other",
            status="succeeded",
            plan={"phase": "completed"},
            plan_hash="a" * 64,
        )
    with patch("apps.agent.retained_review.reopen") as reopen:
        assert (
            env["client"]
            .post(
                f"/api/agent/workflows/{other.id}/retained-review/",
                data={"planHash": "a" * 64},
                content_type="application/json",
                **env["header"],
            )
            .status_code
            == 404
        )
        assert env["client"].post(
            f"/api/agent/workflows/{own.id}/retained-review/",
            data={"planHash": "a" * 64},
            content_type="application/json",
            HTTP_X_PROJECT_ID="1",
        ).status_code in (403, 404)
        assert not reopen.called
        response = env["client"].post(
            f"/api/agent/workflows/{own.id}/retained-review/",
            data={"planHash": "a" * 64},
            content_type="application/json",
            **env["header"],
        )
        assert response.status_code == 200, response.content
        assert reopen.call_args.args[0].id == own.id


def test_current_input_labels_do_not_change_frozen_plan_or_content_revision(
    setup_agent,
):
    from apps.agent.views import workflow_json
    from apps.catalog.models import DataResource
    from apps.agent.workflow import _state_hash

    env = setup_agent
    with project_scope(env["scope"]):
        resource = env["resource"]
        stamp = resource.updated_at
        plan = {
            "phase": "completed",
            "inputs": {"lithology": resource.id},
            "inputNames": {"lithology": "旧登记名称"},
        }
        saved = AgentWorkflow.objects.create(
            owner=env["user"],
            workflow_type="geology_generic",
            model="mock",
            idempotency_key="display-current-label",
            plan=plan,
            plan_hash=_state_hash(plan),
        )
        DataResource.objects.filter(pk=resource.id).update(name="正式地质资料")
        card = workflow_json(saved, view="card")
        assert card["plan"]["inputNames"]["lithology"] == "正式地质资料"
        saved.refresh_from_db()
        resource.refresh_from_db()
        assert saved.plan["inputNames"]["lithology"] == "旧登记名称"
        assert saved.plan_hash == _state_hash(plan)
        assert resource.updated_at == stamp
