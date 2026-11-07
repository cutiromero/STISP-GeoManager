"""Measured rule dispositions, scoped startup authorization and held-object safety."""

import json
from unittest.mock import patch

import pytest
from django.test import RequestFactory, override_settings

from apps.agent.rule_dispositions import build_rule_proposal, automatic_authorized
from apps.agent.input_execution import input_execution_authorized
from apps.compute.packages import ComputeError
from apps.core.client_build import current_browser
from tests.integration.test_demo_decision_batches import scenario
from tests.integration.test_workflow_input_start import ready_mapping, confirm
from tests.integration.test_generic_chat import intake, seed_rules

pytest_plugins = ["tests.integration.test_generic_chat"]


def measured(count=241):
    workflow, stage, results = scenario(count)
    workflow.plan["stages"][0]["results"] = results
    results[0].update(scope="all", rowCount=count)
    for row in results[0]["rows"]:
        row.update(knowledge_id=200, knowledge_revision=3)
    return workflow, stage, results


def test_complete_241_rule_members_do_not_need_a_model_and_keep_exceptions():
    workflow, stage, results = measured()
    for row in results[0]["rows"][-45:]:
        row.update(status="review", suggested_action="review")
    with patch(
        "apps.agent.provider.stream", side_effect=AssertionError("no model request")
    ):
        decision, edits, summary = build_rule_proposal(workflow)
    assert summary["issueCount"] == 241
    assert len(edits) == 196 and summary["retainedIssueCount"] == 45
    assert not {e["issue_id"] for e in edits} & {
        r["issue_id"] for r in results[0]["rows"][-45:]
    }
    assert decision["modelMode"] == "rules"


@pytest.mark.parametrize(
    "change", ["revision", "missing_knowledge", "exception", "conflicting_target"]
)
def test_changed_knowledge_and_ambiguous_objects_never_enter_automatic_edits(change):
    workflow, _, results = measured(2)
    if change == "revision":
        results[0]["rows"][0]["knowledge_revision"] = 99
    elif change == "missing_knowledge":
        results[0]["rows"][0]["knowledge_id"] = 999
    elif change == "exception":
        results[0]["rows"][0]["status"] = "exception"
    else:
        results[0]["rows"][1].update(feature_id="object-0", target_code="other")
    _, edits, _ = build_rule_proposal(workflow)
    assert "issue-0" not in {e["issue_id"] for e in edits}


@pytest.mark.parametrize("change", ["partial", "wrong_task", "count"])
def test_rule_execution_rejects_incomplete_or_foreign_result_sets(change):
    workflow, _, results = measured(2)
    results[0][
        {"partial": "scope", "wrong_task": "taskId", "count": "rowCount"}[change]
    ] = {"partial": "sample", "wrong_task": "foreign", "count": 3}[change]
    with pytest.raises(ComputeError, match="完整实际"):
        build_rule_proposal(workflow)


@pytest.mark.django_db
def test_explicit_automatic_scope_is_bound_to_the_real_input_confirmation(generic):
    workflow, _ = ready_mapping(generic)
    assert (
        confirm(
            generic, workflow, executeAfterMapping=True, applyRuleSuggestions=True
        ).status_code
        == 200
    )
    workflow.refresh_from_db()
    assert workflow.plan["inputExecutionAuthorization"]["applyRuleSuggestions"] is True
    assert input_execution_authorized(workflow, generic["owner"], generic["policy"])
    workflow.plan["executionPolicy"] = "rule_geology_v2"
    assert automatic_authorized(workflow, generic["owner"], generic["policy"])
    workflow.steps.filter(kind="field_mapping_confirmed").delete()
    with pytest.raises(ComputeError, match="授权"):
        automatic_authorized(workflow, generic["owner"], generic["policy"])


@pytest.mark.django_db
@pytest.mark.parametrize("value", ["yes", 1, None])
def test_automatic_scope_flag_rejects_non_booleans(generic, value):
    workflow, _ = ready_mapping(generic)
    assert (
        confirm(
            generic, workflow, executeAfterMapping=True, applyRuleSuggestions=value
        ).status_code
        == 400
    )


@pytest.mark.django_db
def test_automatic_scope_requires_start_authorization(generic):
    workflow, _ = ready_mapping(generic)
    assert confirm(generic, workflow, applyRuleSuggestions=True).status_code == 400
    assert confirm(generic, workflow, executeAfterMapping=True).status_code == 200
    workflow.refresh_from_db()
    workflow.plan["inputExecutionAuthorization"]["applyRuleSuggestions"] = True
    with pytest.raises(ComputeError, match="变化"):
        input_execution_authorized(workflow, generic["owner"], generic["policy"])


@pytest.mark.django_db
def test_combined_review_reuses_complete_roles_and_known_fields_without_a_model(
    generic,
):
    from apps.agent.demo_workflow import prepare_demo

    seed_rules(generic)
    with patch(
        "apps.agent.generic_mapping.model_targets",
        side_effect=AssertionError("known fields need no model"),
    ):
        run, _ = intake(generic, combined=True)
        assert run.research_workflow_id
        workflow = run.research_workflow
        prepare_demo(workflow, generic["owner"], generic["policy"])
    workflow.refresh_from_db()
    assert workflow.plan["phase"] == "review_mapping"
    assert not workflow.execute_operators


def test_stale_browser_entry_is_rejected_without_affecting_api_clients(tmp_path):
    (tmp_path / "index.html").write_text(
        '<script type="module" crossorigin src="/static/index-current.js"></script>'
    )
    factory = RequestFactory()
    with override_settings(DEBUG=False, FRONTEND_DIST=tmp_path, STATIC_ROOT=tmp_path):
        assert not current_browser(factory.post("/", HTTP_SEC_FETCH_MODE="cors"))
        assert not current_browser(
            factory.post(
                "/", HTTP_SEC_FETCH_MODE="cors", HTTP_X_APP_ENTRY="/static/index-old.js"
            )
        )
        assert current_browser(
            factory.post(
                "/",
                HTTP_SEC_FETCH_MODE="cors",
                HTTP_X_APP_ENTRY="/static/index-current.js",
            )
        )
        assert current_browser(factory.post("/"))
        assert not current_browser(
            factory.post("/", HTTP_ORIGIN="http://101.42.12.157:41312")
        )
        assert not current_browser(factory.post("/", HTTP_USER_AGENT="Mozilla/5.0"))
        assert current_browser(
            factory.post(
                "/",
                HTTP_ORIGIN="http://101.42.12.157:41312",
                HTTP_X_APP_ENTRY="/static/index-current.js",
            )
        )


@pytest.mark.django_db
def test_automatic_execution_writes_only_authorized_rule_rows_and_requires_its_proof(
    generic, monkeypatch
):
    import csv
    from apps.agent.demo_workflow import prepare_demo, _save
    from apps.agent.rule_dispositions import authorize_rule_execution
    from apps.agent.geology_multi_review import freeze_proposal, create_approved_changes
    from apps.core.storage import table_data_path

    workflow, _ = ready_mapping(generic)
    assert (
        confirm(
            generic, workflow, executeAfterMapping=True, applyRuleSuggestions=True
        ).status_code
        == 200
    )
    workflow.refresh_from_db()
    prepare_demo(workflow, generic["owner"], generic["policy"])
    workflow.refresh_from_db()
    entry = workflow.evidence[0]
    _, _, results = measured(2)
    for row in results[0]["rows"]:
        row.update(
            rule_id=entry["trialBinding"]["ruleId"],
            rule_version=entry["trialBinding"]["ruleVersion"],
            knowledge_id=entry["id"],
            knowledge_revision=entry["revision"],
        )
    results[0]["rows"][1].update(
        status="exception",
        suggested_action="review",
        candidate_action="set_code",
        candidate_target_code="T3",
    )
    check, stage = workflow.plan["stages"][:2]
    check.update(taskId="task", results=results)
    workflow.plan.update(stageIndex=1)
    decision, edits, _ = build_rule_proposal(workflow)
    stage.update(decision=decision, edits=edits, executionMode="rule_verified")
    freeze_proposal(workflow, stage)
    assert authorize_rule_execution(
        workflow, generic["owner"], generic["policy"], stage
    )
    assert not workflow.steps.filter(kind="modifications_approved").exists()
    _save(workflow)
    monkeypatch.setattr(
        "apps.agent.geology_multi_review.read_results", lambda *a, **k: results
    )
    assert workflow.status == "waiting_approval"
    from apps.agent.geology_multi_review import approve_modifications

    approve_modifications(
        workflow, generic["owner"], generic["policy"], [], workflow.plan_hash
    )
    workflow.status = "queued"
    _save(workflow)
    resource = create_approved_changes(
        workflow, generic["owner"], generic["policy"], stage
    )
    records = list(
        csv.DictReader(
            table_data_path(resource.storage_path.removeprefix("table/")).open()
        )
    )
    assert len(records) == 1 and records[0]["issue_id"] == "issue-0"
    assert records[0]["action"] == "set_code"
    workflow.steps.filter(kind="modifications_approved").delete()
    with pytest.raises(ComputeError, match="有效批准"):
        create_approved_changes(workflow, generic["owner"], generic["policy"], stage)


def test_report_projection_preserves_real_totals_and_knowledge_conditions():
    from apps.agent.rule_dispositions import report_payload

    workflow, _, results = measured(241)
    knowledge = workflow.evidence[0]
    payload = {
        "knowledge": [],
        "actualResults": [
            {
                "kind": "table",
                "key": "statistics",
                "outputId": 2,
                "taskId": "t",
                "rows": [{"issues": 241, "remaining": 45}],
                "rowCount": 1,
                "metadata": {"irrelevant": "x" * 100000},
            },
            {
                "kind": "raster",
                "key": "corrected",
                "outputId": 3,
                "taskId": "t",
                "checksum": "c",
                "metadata": {"style": "x" * 100000},
            },
        ],
        "availableEvidence": [
            {"kind": "knowledge", "id": "200"},
            {"kind": "output", "id": "2"},
            {"kind": "output", "id": "3"},
        ],
    }
    projected = report_payload(payload, workflow)
    assert projected["actualResults"][0]["rows"] == [{"issues": 241, "remaining": 45}]
    assert projected["knowledge"][0]["conditions"] == knowledge["conditions"]
    assert projected["knowledge"][0]["exceptions"] == knowledge["exceptions"]
    assert len(projected["actualResults"]) == 1
    assert not any("metadata" in item for item in projected["actualResults"])
    assert len(json.dumps(projected)) < 5000


def test_report_collapses_review_samples_without_changing_approved_counts():
    from apps.agent.rule_dispositions import report_payload

    workflow, _, _ = measured(241)
    payload = {
        "knowledge": [],
        "actualResults": [],
        "availableEvidence": [],
        "modificationReview": {
            "approvedCount": 196,
            "suggestionCount": 241,
            "approvalScopeDigest": "scope",
            "suggestions": {"rows": ["unneeded sampled object details"] * 241},
            "groups": [
                {
                    "element": "lithology",
                    "ruleId": "L-03",
                    "action": "set_code",
                    "count": 1,
                    "approvedCount": int(i < 196),
                }
                for i in range(241)
            ],
        },
    }
    review = report_payload(payload, workflow)["modificationReview"]
    assert review["approvedCount"] == 196 and review["suggestionCount"] == 241
    assert review["groups"] == [
        {
            "element": "lithology",
            "ruleId": "L-03",
            "action": "set_code",
            "count": 241,
            "approvedCount": 196,
        }
    ]
    assert (
        "suggestions" not in review and review["scope"] == "complete_rule_action_counts"
    )


def test_report_facts_distinguish_dispositions_from_remaining_issues():
    from apps.agent.rule_dispositions import report_payload

    workflow, stage, _ = measured(241)
    stage["taskId"] = "apply-task"
    workflow.plan["stages"].append({"name": "recheck", "taskId": "recheck-task"})
    payload = {
        "knowledge": [],
        "availableEvidence": [],
        "actualResults": [
            {
                "kind": "table",
                "key": "issues",
                "taskId": "task",
                "rowCount": 241,
                "rows": [],
                "outputId": 1,
            },
            {
                "kind": "table",
                "key": "issues",
                "taskId": "recheck-task",
                "rowCount": 142,
                "rows": [],
                "outputId": 2,
            },
            {
                "kind": "table",
                "key": "changes",
                "taskId": "apply-task",
                "rowCount": 196,
                "rows": [
                    {"action": "downweight", "count": 104},
                    {"action": "exclude", "count": 49},
                    {"action": "reclassify", "count": 38},
                    {"action": "set_code", "count": 5},
                ],
                "outputId": 3,
            },
        ],
    }
    facts = report_payload(payload, workflow)["verifiedReportFacts"]
    assert (
        facts["initialIssueCount"],
        facts["executedDispositionCount"],
        facts["recheckRemainingIssueCount"],
    ) == (241, 196, 142)
    assert (
        facts["executedActions"]["reclassify"] == 38
        and facts["executedActions"]["set_code"] == 5
    )
