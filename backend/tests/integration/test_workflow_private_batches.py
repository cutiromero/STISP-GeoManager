"""Every workflow view hides private batch requests without losing public facts."""

import copy
import json
from unittest.mock import patch

import pytest

from apps.agent.models import AgentWorkflow, AgentWorkflowStep
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent as setup_agent


pytestmark = pytest.mark.django_db
PRIVATE_MARKER = "private-batch-request-scope-and-raw-response"


def workflow_plan():
    edit = {
        "feature_id": "S00001",
        "rule_id": "S-01",
        "action": "exclude",
        "weight": 0,
        "target_code": "",
    }
    task_id = "67ac90d1-999f-44b7-9b68-1da1f726a142"
    return {
        "phase": "completed",
        "stageIndex": 1,
        "stages": [
            {
                "name": "apply",
                "status": "completed",
                "taskId": task_id,
                "outputs": [{"key": "final_faults", "kind": "vector", "outputId": 1}],
                "decision": {"summary": "已按批准范围完成修改"},
                "approvedEdits": [edit],
                "modelAttempts": [
                    {
                        "status": "accepted",
                        "requested": True,
                        "inputTokens": 700,
                        "response": PRIVATE_MARKER,
                    }
                ],
                "results": [
                    {
                        "key": "changes",
                        "kind": "table",
                        "taskId": task_id,
                        "outputId": 2,
                        "checksum": "a" * 64,
                        "scope": "all",
                        "rowCount": 1,
                        "rows": [{**edit, "actual_changed": "True", "new_code": ""}],
                    }
                ],
            }
        ],
        "finalStage": {
            "name": "final_analysis",
            "status": "completed",
            "decision": {"summary": "已核验本轮成果"},
            "modelRequestPayload": {"private": PRIVATE_MARKER},
            "modelAttempts": [{"response": PRIVATE_MARKER}],
            "modelBudgetHistory": [{"response": PRIVATE_MARKER}],
            "edits": [PRIVATE_MARKER],
            "proposedEdits": [PRIVATE_MARKER],
        },
        "modificationReview": {
            "proposalHash": "frozen",
            "approvedSuggestionIds": ["chosen"],
            "unapprovedSuggestionIds": [],
            "suggestions": [
                {
                    "id": "chosen",
                    "featureId": "S00001",
                    "ruleId": "S-01",
                    "element": "structure",
                    "action": "exclude",
                    "status": "suggested",
                    "reason": "本轮测量和规则对应的建议",
                    "preview": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [98, 35],
                                [98.01, 35],
                                [98.01, 35.01],
                                [98, 35.01],
                                [98, 35],
                            ]
                        ],
                    },
                }
            ],
        },
    }


def private_batches(size, count):
    secret = PRIVATE_MARKER + "x" * size
    return {
        "sourceSha256": secret,
        "cursor": count,
        "memberCount": count,
        "coveredMemberCount": count,
        "status": "completed",
        "batches": [
            {
                "start": index,
                "end": index + 1,
                "scopeSha256": secret,
                "stage": {
                    "modelRequestPayload": {"members": secret},
                    "modelAttempts": [{"response": secret}],
                    "unrequestedBudgetAttempts": [{"response": secret}],
                    "decision": {"edits": [secret]},
                },
            }
            for index in range(count)
        ],
    }


@pytest.mark.parametrize(
    "scenario", ["geology_generic", "geology_multi_element_reasoning"]
)
@pytest.mark.parametrize("view", ["full", "card", "compare", "inspection"])
def test_private_batch_payload_never_changes_public_workflow_response(
    setup_agent, scenario, view
):
    env = setup_agent
    with project_scope(env["scope"]):
        workflow = AgentWorkflow.objects.create(
            owner=env["user"],
            model="mock",
            workflow_type=scenario,
            status="succeeded",
            plan=workflow_plan(),
        )
        AgentWorkflowStep.objects.create(
            workflow=workflow,
            sequence=1,
            kind="model_activity",
            status="succeeded",
            action={"stage": "apply", "attempt": 1},
            output_refs={
                "modelActivity": {
                    "status": "complete",
                    "thinkingText": "测试模型返回的思考片段",
                }
            },
        )
    url = f"/api/agent/workflows/{workflow.id}/?view={view}"
    if view == "compare":
        url += "&limit=25"
    with patch("apps.agent.workflow.authorize_workflow_history"):
        baseline = env["client"].get(url, **env["header"])
        assert baseline.status_code == 200
        expected = baseline.json()
        assert PRIVATE_MARKER not in json.dumps(expected)
        for size, count in ((1, 1), (8000, 25)):
            with project_scope(env["scope"]):
                batches = private_batches(size, count)
                workflow.plan["stages"][0]["modelBatches"] = copy.deepcopy(batches)
                workflow.plan["finalStage"]["modelBatches"] = batches
                workflow.save(update_fields=["plan"])
                saved = copy.deepcopy(workflow.plan)
            response = env["client"].get(url, **env["header"])
            assert response.status_code == 200
            assert response.json() == expected
            assert len(response.content) == len(baseline.content)
            assert "modelBatches" not in response.content.decode()
            with project_scope(env["scope"]):
                workflow.refresh_from_db()
                assert workflow.plan == saved
    assert expected["modelActivity"]["thinkingText"] == "测试模型返回的思考片段"
    assert expected["plan"]["stages"][0]["outputs"][0]["key"] == "final_faults"
    if view in {"full", "inspection"}:
        assert (
            expected["plan"]["stages"][0]["decision"]["summary"]
            == "已按批准范围完成修改"
        )
        assert expected["plan"]["finalStage"]["decision"]["summary"] == "已核验本轮成果"
    if view == "full":
        assert (
            expected["plan"]["stages"][0]["approvedEdits"][0]["feature_id"] == "S00001"
        )
    if view == "compare":
        assert expected["plan"]["pagination"]["total"] == 1
        assert len(expected["plan"]["compareFeatures"]["features"]) == 1
    if view == "inspection":
        assert expected["plan"]["stages"][0]["modelAttempts"] == [
            {
                "status": "accepted",
                "requested": True,
                "inputTokens": 700,
                "responseSaved": True,
            }
        ]
