"""Project-bound trial knowledge, approval scope and repeatable multi-element plans."""

# ruff: noqa: F811
import copy
import csv
import io
import json
import uuid
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied

from apps.agent.geology_multi import SCENARIO, ROLES, FIELDS, graph, prepare
from apps.agent.geology_multi_review import (
    approve_modifications,
    create_approved_changes,
    freeze_proposal,
    validate_edits,
    assess_edits,
)
from apps.agent.geology_multi_results import table_rows
from apps.agent.models import AgentWorkflow
from apps.catalog.models import DataResource
from apps.compute.packages import ComputeError
from apps.compute.models import AlgorithmResource, AlgorithmVersion
from apps.compute.packages import validate_manifest
from apps.core.storage import table_data_path
from apps.knowledge.models import KnowledgeEntry, KnowledgeRevision
from apps.knowledge.services import visible_entries, serialize
from apps.knowledge.trial_rules import read_bound_rules, authorize_trial_evidence
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo  # noqa: F401

pytestmark = pytest.mark.django_db


def test_freezing_rules_requires_project_write_permission_before_any_write(multi):
    env = multi
    owner = env["owner"]
    owner.user_permissions.remove(
        Permission.objects.get(
            codename="add_dataresource", content_type__app_label="catalog"
        )
    )
    owner = get_user_model().objects.get(pk=owner.pk)
    workflow = env["workflow"]
    workflow.pk = uuid.uuid4()
    path = table_data_path(f"demo/workflows/{workflow.id}/trial-rules.csv")
    before = DataResource.objects.count()
    with pytest.raises(ComputeError, match="catalog.add_dataresource"):
        prepare(workflow, owner, env["policy"])
    assert DataResource.objects.count() == before
    assert not path.exists()


def csv_bytes(columns, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


@pytest.fixture
def multi(demo, monkeypatch):
    user, project = demo["owner"], demo["project"]
    entries = []
    for rule_id in ("L-03", "A-01"):
        entry = KnowledgeEntry.objects.create(
            title=rule_id + " 本案例试用",
            domain="geology",
            status="draft",
            statement="先核对观测与条件，例外保留。",
            conditions=["本示范区"],
            exceptions=["依据不足时保留"],
            sources=[{"title": "项目整理规则", "locator": rule_id}],
            rule_config={
                "trialScope": {
                    "scenario": SCENARIO,
                    "projectId": project.id,
                    "ruleId": rule_id,
                    "ruleVersion": "0.1-draft",
                },
                "parameters": {"threshold": 0.5},
                "rule": {"id": rule_id},
            },
        )
        entries.append(entry)
    rows = [
        {
            "rule_id": entry.rule_config["trialScope"]["ruleId"],
            "rule_version": "0.1-draft",
            "knowledge_id": entry.id,
            "knowledge_revision": entry.revision,
            "params_json": '{"threshold":999}',
            "rule_json": '{"id":"client-forgery"}',
            "units_json": '{"T3":{"name":"地层"}}' if i == 0 else "",
            "aliases_json": '{"地层":"T3"}' if i == 0 else "",
        }
        for i, entry in enumerate(entries)
    ]
    path = table_data_path("multi/input-rules.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(csv_bytes(FIELDS, rows))
    inputs = {}
    for role, kind in ROLES.items():
        resource = DataResource.objects.create(
            name=role,
            code="geology-multi-" + role,
            data_type=kind,
            storage_path="table/multi/input-rules.csv" if role == "rules" else "",
            file_format="CSV" if role == "rules" else "GPKG",
            maintainer=user,
        )
        inputs[role] = resource.id
    monkeypatch.setattr(
        "apps.agent.geology_multi.candidate",
        lambda resource: {
            "fields": ["feature_id", "name", "geo_sym", "line_id"],
            "crs": "EPSG:32646",
            "geometryTypes": ["LineString"]
            if resource.id == inputs["faults"]
            else ["Polygon"],
        },
    )
    workflow = AgentWorkflow.objects.create(
        owner=user,
        model="mock",
        workflow_type=SCENARIO,
        goal="检查海德乌拉案例",
        max_iterations=12,
        max_operator_steps=12,
        resource_ids=list(inputs.values()),
        parameters={"segment": "all"},
        plan={"inputs": inputs},
        idempotency_key="multi-review-test",
    )
    workflow.evidence = prepare(workflow, user, demo["policy"])
    workflow.plan.update(
        inputSnapshots={
            role: DataResource.objects.get(pk=identity).updated_at.isoformat()
            for role, identity in inputs.items()
        },
        algorithms={"geology-multi-apply": {"versionId": 1, "checksum": "a" * 64}},
    )
    yield {
        **demo,
        "workflow": workflow,
        "entries": entries,
        "inputs": inputs,
        "rows": rows,
    }


def test_trial_drafts_are_explicit_and_do_not_enter_ordinary_retrieval(multi):
    wf, user = multi["workflow"], multi["owner"]
    assert (
        not visible_entries(user)
        .filter(pk__in=[e.id for e in multi["entries"]])
        .exists()
    )
    assert authorize_trial_evidence(wf, user) == {e.id for e in multi["entries"]}
    bound = [
        {key: row[key] for key in ("id", "revision", "ruleId", "ruleVersion")}
        for row in wf.plan["trialRuleBindings"]
    ]
    with pytest.raises(PermissionDenied):
        read_bound_rules(user, wf.project_tag_id, "geology_map_review", bound)
    bound[0]["revision"] += 1
    with pytest.raises(PermissionDenied):
        read_bound_rules(user, wf.project_tag_id, SCENARIO, bound)


def test_server_freezes_knowledge_parameters_not_client_csv(multi):
    wf = multi["workflow"]
    path = table_data_path(f"demo/workflows/{wf.id}/trial-rules.csv")
    rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))
    assert all(json.loads(row["params_json"])["threshold"] == 0.5 for row in rows)
    assert json.loads(rows[0]["rule_json"])["id"] == "L-03"
    multi["entries"][0].statement = "同修订擅改正文"
    multi["entries"][0].save()
    with pytest.raises(PermissionDenied, match="已变化"):
        authorize_trial_evidence(wf, multi["owner"])


def test_history_reads_archived_trial_revision_while_execution_rejects_changes(multi):
    wf, user = multi["workflow"], multi["owner"]
    entry = multi["entries"][0]
    KnowledgeRevision.objects.create(
        entry=entry,
        revision=entry.revision,
        snapshot=serialize(entry),
    )
    entry.revision += 1
    entry.statement = "经审查更新后的说明"
    entry.status = "published"
    entry.save()
    with pytest.raises(PermissionDenied):
        authorize_trial_evidence(wf, user)
    assert authorize_trial_evidence(wf, user, history=True) == {
        item.id for item in multi["entries"]
    }
    wf.evidence[0]["statement"] = "被篡改的历史引用"
    with pytest.raises(PermissionDenied):
        authorize_trial_evidence(wf, user, history=True)


def fixture_review(multi):
    wf = multi["workflow"]
    rows = []
    edits = []
    for index, (rule_id, action) in enumerate(
        (("L-03", "set_code"), ("A-01", "downweight"))
    ):
        rows.append(
            {
                "issue_id": f"I{index}",
                "element": "lithology" if index == 0 else "alteration",
                "feature_id": f"N{index}",
                "rule_id": rule_id,
                "rule_version": "0.1-draft",
                "snapshot_hash": "b" * 64,
                "allowed_actions_json": json.dumps([action, "review", "keep"]),
                "suggested_action": action,
                "target_code": "T3" if index == 0 else "",
                "measurements_json": '{"area_m2":100}',
                "reason": "实际属性与试用规则存在差异",
                "geometry_json": '{"type":"Polygon","coordinates":[[[90,30],[91,30],[91,31],[90,31],[90,30]]]}',
            }
        )
        edits.append(
            {
                "issue_id": f"I{index}",
                "action": action,
                "target_code": "T3" if index == 0 else "",
                "weight": 1 if index == 0 else 0.5,
                "reason": "依据当前测量、试用规则及必要例外提出建议",
            }
        )
    results = [
        {
            "key": "issues",
            "outputId": 2,
            "taskId": "task",
            "checksum": "c" * 64,
            "rows": rows,
        }
    ]
    check = {
        "name": "check",
        "identifier": "geology-multi-check",
        "taskId": "task",
        "results": results,
    }
    apply = {
        "name": "apply",
        "identifier": "geology-multi-apply",
        "parameters": {"segment": "all"},
        "edits": edits,
        "decision": {
            "evidenceRefs": [
                {"kind": "knowledge", "id": str(e.id)} for e in multi["entries"]
            ]
        },
    }
    wf.plan.update(stages=[check, apply], stageIndex=1)
    freeze_proposal(wf, apply)
    return wf, apply, results


def test_approval_only_writes_selected_object_action(multi, monkeypatch):
    wf, stage, results = fixture_review(multi)
    monkeypatch.setattr(
        "apps.agent.geology_multi_review.read_results", lambda *args: results
    )
    monkeypatch.setattr(
        "apps.agent.geology_multi_review.authorized_task",
        lambda *args: SimpleNamespace(),
    )
    selected = [wf.plan["modificationReview"]["suggestions"][1]["id"]]
    approve_modifications(wf, multi["owner"], multi["policy"], selected, "hash")
    resource = create_approved_changes(wf, multi["owner"], multi["policy"], stage)
    path = table_data_path(resource.storage_path.removeprefix("table/"))
    records = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))
    assert len(records) == 1
    assert records[0]["feature_id"] == "N1"
    assert records[0]["action"] == "downweight"
    assert float(records[0]["weight"]) == 0.5
    stage["parameters"]["segment"] = "lithology"
    with pytest.raises(ComputeError, match="有效批准"):
        create_approved_changes(wf, multi["owner"], multi["policy"], stage)


def test_large_group_approval_fixes_all_selected_rows_not_thirty(multi, monkeypatch):
    from apps.agent.geology_issue_groups import group_summaries

    wf, stage, results = fixture_review(multi)
    template = results[0]["rows"][1]
    results[0]["rows"] = [
        {
            **template,
            "issue_id": f"I{index}",
            "feature_id": f"N{index}",
            "status": "suggested",
        }
        for index in range(180)
    ]
    group = group_summaries(results[0]["rows"])[0]
    stage["edits"] = [
        {
            "group_id": group["group_id"],
            "disposition": "suggested",
            "excluded_issue_ids": ["I179"],
            "reason": "按实际测量降权，保留需核实对象",
        }
    ]
    accepted, report = assess_edits(
        stage["edits"], results, workflow=wf, decision=stage["decision"]
    )
    assert len(accepted) == 179 and not report["errors"]
    stage["edits"] = [
        {
            key: row[key]
            for key in ("issue_id", "action", "target_code", "weight", "reason")
        }
        for row in accepted
    ]
    freeze_proposal(wf, stage)
    monkeypatch.setattr(
        "apps.agent.geology_multi_review.read_results", lambda *args: results
    )
    monkeypatch.setattr(
        "apps.agent.geology_multi_review.authorized_task",
        lambda *args: SimpleNamespace(),
    )
    selected = [item["id"] for item in wf.plan["modificationReview"]["suggestions"]][
        :-1
    ]
    approve_modifications(wf, multi["owner"], multi["policy"], selected, "hash")
    resource = create_approved_changes(wf, multi["owner"], multi["policy"], stage)
    assert resource.item_count == 178
    assert len(stage["approvedEdits"]) == 178


def test_http_confirmation_accepts_large_multi_selection_only(
    multi, client, monkeypatch
):
    wf, _, _ = fixture_review(multi)
    wf.plan_hash = "group-plan"
    wf.save()
    accepted = []
    monkeypatch.setattr(
        "apps.agent.views.require_access", lambda *args: multi["policy"]
    )
    monkeypatch.setattr(
        "apps.agent.demo_workflow.confirm_demo",
        lambda workflow, user, policy, plan_hash, selected, mapping: accepted.extend(
            selected
        ),
    )
    client.force_login(multi["owner"])
    ids = [f"s-{index}" for index in range(180)]
    response = client.post(
        f"/api/agent/workflows/{wf.id}/confirm/",
        {"planHash": "group-plan", "selectedSuggestionIds": ids},
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(wf.project_tag_id),
    )
    assert response.status_code == 200 and accepted == ids
    wf.workflow_type = "geology_map_review"
    wf.save(update_fields=["workflow_type"])
    response = client.post(
        f"/api/agent/workflows/{wf.id}/confirm/",
        {"planHash": "group-plan", "selectedSuggestionIds": ids},
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(wf.project_tag_id),
    )
    assert response.status_code == 400


def test_multi_detail_gzip_keeps_complete_approval_scope(multi, client, monkeypatch):
    import gzip

    wf, stage, _ = fixture_review(multi)
    stage["approvedEdits"] = stage["proposedEdits"]
    wf.save()
    client.force_login(multi["owner"])
    monkeypatch.setattr(
        "apps.agent.workflow.authorize_workflow_history", lambda *args: None
    )
    response = client.get(
        f"/api/agent/workflows/{wf.id}/",
        HTTP_X_PROJECT_ID=str(wf.project_tag_id),
        HTTP_ACCEPT_ENCODING="gzip",
    )
    assert response.status_code == 200
    assert response["Content-Encoding"] == "gzip"
    value = json.loads(gzip.decompress(response.content))
    assert value["plan"]["stages"][1]["approvedEdits"] == stage["approvedEdits"]
    assert (
        value["modificationReview"]["suggestions"]
        == wf.plan["modificationReview"]["suggestions"]
    )


def test_no_approval_cannot_execute_and_empty_selection_retains_all(multi, monkeypatch):
    wf, stage, results = fixture_review(multi)
    monkeypatch.setattr(
        "apps.agent.geology_multi_review.read_results", lambda *args: results
    )
    monkeypatch.setattr(
        "apps.agent.geology_multi_review.authorized_task",
        lambda *args: SimpleNamespace(),
    )
    with pytest.raises(ComputeError, match="有效批准"):
        create_approved_changes(wf, multi["owner"], multi["policy"], stage)
    approve_modifications(wf, multi["owner"], multi["policy"], [], "hash")
    resource = create_approved_changes(wf, multi["owner"], multi["policy"], stage)
    assert resource.item_count == 0
    assert wf.plan["modificationReview"]["unapprovedSuggestionIds"]


def test_identical_edits_are_normalized_and_deduplicated(multi):
    _, stage, results = fixture_review(multi)
    original = copy.deepcopy(stage["edits"])
    edits = copy.deepcopy(original)
    edits[1]["target_code"] = "不应改变类别"
    edits.append(copy.deepcopy(original[1]))
    rows, assessment = assess_edits(edits, results)
    assert len(rows) == 2 and rows[1]["target_code"] == ""
    assert assessment == {
        "discardedCount": 0,
        "errors": [],
        "duplicateCount": 1,
        "duplicateIndices": [3],
    }
    assert stage["edits"] == original
    assert edits[1]["target_code"] == "不应改变类别"


@pytest.mark.parametrize(
    "action,weight", [("keep", 1), ("review", 1), ("downweight", 0.5), ("exclude", 0)]
)
def test_non_category_actions_ignore_target_code(multi, action, weight):
    _, stage, results = fixture_review(multi)
    results[0]["rows"][1]["allowed_actions_json"] = json.dumps([action])
    edit = {
        **stage["edits"][1],
        "action": action,
        "weight": weight,
        "target_code": "T3",
    }
    assert validate_edits([edit], results)[0]["target_code"] == ""
    assert edit["target_code"] == "T3"


def test_conflicting_object_actions_keep_first_valid_edit(multi):
    _, stage, results = fixture_review(multi)
    first = stage["edits"][0]
    same_issue = {**first, "action": "keep", "target_code": ""}
    other_issue = {**results[0]["rows"][0], "issue_id": "other"}
    results[0]["rows"].append(other_issue)
    rows, assessment = assess_edits(
        [first, same_issue, {**same_issue, "issue_id": "other"}], results
    )
    assert len(rows) == 1 and rows[0]["action"] == "set_code"
    assert [item["index"] for item in assessment["errors"]] == [2, 3]
    assert "唯一" in assessment["errors"][0]["reason"]
    assert "保留首个合格建议" in assessment["errors"][1]["reason"]


@pytest.mark.parametrize(
    "mode", ["mixed", "all_invalid", "missing_knowledge", "recovered"]
)
@pytest.mark.parametrize(
    "workflow_type", ["geology_multi_element_reasoning", "geology_generic"]
)
def test_multi_retry_reports_each_error_and_preserves_only_valid_edits(
    multi, settings, mode, workflow_type
):
    from apps.agent.demo_decisions import decide
    from apps.agent.policy import default_policy
    from tests.integration.test_demo_decision_retry import run
    from tests.integration.test_demo_edit_context import model_response

    settings.AGENT_MODELS = [
        {
            "alias": "mock",
            "name": "真实接口测试",
            "model_id": "qwen-fixture",
            "base_url": "http://127.0.0.1:19100/v1",
            "agent": True,
        }
    ]
    wf, stage, results = fixture_review(multi)
    wf.workflow_type = workflow_type
    edits = stage.pop("edits")
    decision = stage.pop("decision")
    answer = model_response("geology-multi-apply", [])
    answer["decision"]["evidenceRefs"] = [
        {"kind": "output", "id": "2"},
        *decision["evidenceRefs"],
    ]
    invalid = [{**edits[0], "issue_id": "missing"}, {**edits[1], "weight": 2}]
    if mode == "missing_knowledge":
        answer["decision"]["evidenceRefs"] = answer["decision"]["evidenceRefs"][:2]
        answer["edits"] = edits
    else:
        answer["edits"] = invalid if mode == "all_invalid" else [edits[0], *invalid]
    before = copy.deepcopy(answer)
    if mode == "all_invalid":
        with pytest.raises(ComputeError, match="第1项.*missing.*第2项.*I1"):
            run([answer, answer], wf, stage, results)
        assert all(not attempt["accepted"] for attempt in stage["modelAttempts"])
        return
    (accepted_decision, accepted), requests = run([answer, answer], wf, stage, results)
    assert accepted == [edits[0]]
    assessment = stage["editValidation"]
    assert assessment["discardedCount"] == (1 if mode == "missing_knowledge" else 2)
    feedback = json.loads(requests[1][-1]["content"])
    assert feedback["invalidEdits"] == assessment["errors"]
    if mode != "missing_knowledge":
        assert [item["index"] for item in feedback["invalidEdits"]] == [2, 3]
        assert [item["issue_id"] for item in feedback["invalidEdits"]] == [
            "missing",
            "I1",
        ]
        assert "实际检查" in feedback["validationError"]
        assert "权重范围" in feedback["validationError"]
    assert answer == before
    assert stage["modelAttempts"][-1]["accepted"]
    assert not wf.plan["modificationReview"]["approvedSuggestionIds"]
    if mode == "recovered":
        audit = copy.deepcopy(stage["modelAttempts"])
        wf.max_iterations = wf.iteration = 2
        wf.plan["actualModelCallCount"] = 2
        with patch("apps.agent.demo_decisions.resource_context", return_value=[]):
            _, recovered = decide(
                wf, None, default_policy(), stage, results, lambda: None
            )
        assert recovered == accepted
        assert stage["modelAttempts"] == audit
        assert stage["editValidation"] == assessment
    stage.update(edits=accepted, decision=accepted_decision)
    freeze_proposal(wf, stage)
    assert wf.status == "waiting_approval"
    assert len(wf.plan["modificationReview"]["suggestions"]) == 1
    assert not wf.plan["modificationReview"]["approvedSuggestionIds"]
    wf.save(update_fields=["plan", "status"])
    wf.refresh_from_db()
    assert wf.plan["stages"][1]["editValidation"] == assessment


def test_model_cannot_change_target_or_turn_downweight_into_delete(multi):
    _, stage, results = fixture_review(multi)
    changed = copy.deepcopy(stage["edits"])
    changed[0]["target_code"] = "arbitrary"
    with pytest.raises(ComputeError, match="目标代号"):
        validate_edits(changed, results)
    changed = copy.deepcopy(stage["edits"])
    changed[1]["weight"] = 0
    with pytest.raises(ComputeError, match="降权"):
        validate_edits(changed, results)


def test_each_segment_shares_inputs_and_explicit_upstream_bindings():
    assert len(graph("lithology")) == 3
    assert len(graph("structure")) == 4
    assert len(graph("alteration")) == len(graph("all")) == 5
    assert graph("all")[-1][2]["lithology"] == "apply/lithology"
    assert graph("structure")[-1][2]["faults"] == "apply/faults"


def test_large_actual_issue_table_keeps_rule_counts_and_labels_sample(tmp_path):
    path = tmp_path / "issues.csv"
    rows = [
        {"issue_id": str(i), "rule_id": "L-03" if i < 100 else "A-01"}
        for i in range(300)
    ]
    path.write_bytes(csv_bytes(("issue_id", "rule_id"), rows))
    value = table_rows(path, "issues")
    assert value["rowCount"] == 300
    assert value["countsByRule"] == {"L-03": 100, "A-01": 200}
    assert value["scope"] == "all"
    assert len(value["rows"]) == 300


def test_representative_issues_use_actual_size_without_hiding_total(tmp_path):
    path = tmp_path / "issues.csv"
    columns = ("issue_id", "rule_id", "measurements_json")
    rows = [
        {
            "issue_id": f"l-{size}",
            "rule_id": "L-03",
            "measurements_json": json.dumps({"area_m2": size}),
        }
        for size in (1, 80, 2, 100)
    ] + [
        {
            "issue_id": f"s-{size}",
            "rule_id": "S-02",
            "measurements_json": json.dumps({"length_m": size}),
        }
        for size in (3, 200, 20)
    ]
    path.write_bytes(csv_bytes(columns, rows))
    result = table_rows(path, "issues")
    assert result["rowCount"] == 7
    assert result["countsByRule"] == {"L-03": 4, "S-02": 3}
    assert result["rows"] == rows
    assert result["scope"] == "all"


@pytest.mark.parametrize("missing_faults", [False, True])
def test_native_published_manifests_prepare_the_actual_stage_protocol(
    multi, missing_faults
):
    from apps.agent.demo_workflow import prepare_demo, confirm_demo

    root = Path(__file__).resolve().parents[3]
    for suffix in ("check", "apply", "relations", "prospect"):
        manifest = validate_manifest(
            json.loads(
                (
                    root / f"examples/compute/geology-multi-{suffix}/operator.yaml"
                ).read_text(encoding="utf-8")
            )
        )
        algorithm = AlgorithmResource.objects.create(
            identifier=manifest["identifier"],
            name=manifest["name"],
            created_by=multi["owner"],
        )
        AlgorithmVersion.objects.create(
            algorithm=algorithm,
            version="1.0.0",
            status="published",
            manifest=manifest,
            checksum="d" * 64,
            runtime_digest="sha256:" + "a" * 64,
        )
    wf = multi["workflow"]
    if missing_faults:
        wf.workflow_type = "geology_generic"
        wf.plan.update(
            phase="inputs_ready",
            workingCopies={"faults": multi["inputs"]["faults"]},
            missingRoles=["faults"],
            uploadInputs={"lithology": multi["inputs"]["lithology"]},
        )
    prepare_demo(wf, multi["owner"], multi["policy"])
    assert wf.status == "waiting_approval"
    assert [stage["name"] for stage in wf.plan["stages"]] == [
        "check",
        "apply",
        "recheck",
        "relations",
        "prospect",
    ]
    assert wf.plan["stages"][0]["bindings"]["rules"] == "frozen_rules"
    assert wf.plan["stages"][2]["bindings"]["alterations"] == "apply/alterations"
    assert wf.plan["stages"][2]["bindings"]["faults"] == (
        "faults" if missing_faults else "apply/faults"
    )
    assert wf.plan["stages"][4]["bindings"]["before_lithology"] == "lithology"
    assert wf.plan["stages"][4]["parameters"]["segment"] == "all"
    assert len(wf.plan["upstreamVersions"]) == 9
    confirm_demo(wf, multi["owner"], multi["policy"], wf.plan_hash)
    assert wf.status == "queued"
    assert wf.execute_operators is True


def test_missing_optional_upstream_is_omitted_without_reusing_original():
    from apps.agent.demo_workflow import _inputs

    workflow = SimpleNamespace(
        plan={
            "inputs": {"faults": 10},
            "algorithms": {
                "next": {
                    "manifest": {
                        "inputs": [
                            {"key": "faults", "required": True},
                            {"key": "intersections", "required": False},
                        ]
                    }
                }
            },
            "stages": [
                {"name": "apply", "outputs": []},
                {"name": "relations", "outputs": []},
            ],
        }
    )
    stage = {
        "identifier": "next",
        "bindings": {"faults": "faults", "intersections": "relations/intersections"},
    }
    assert _inputs(workflow, stage) == {"faults": 10}
    stage["bindings"]["faults"] = "apply/faults"
    with pytest.raises(ComputeError, match="apply/faults"):
        _inputs(workflow, stage)


def test_before_approval_map_does_not_claim_a_corrected_result(multi):
    from apps.agent.geology_multi_review import update_map

    wf, _, _ = fixture_review(multi)
    wf.plan["stages"][0]["outputs"] = [
        {"key": "issue_lithology", "kind": "vector", "resourceId": 100}
    ]
    update_map(wf)
    assert "after" not in wf.plan["multiElementMap"]
    assert "changes" not in wf.plan["multiElementMap"]
    assert wf.plan["multiElementMap"]["checks"] == [100]


@pytest.mark.parametrize("empty", [False, True])
def test_map_uses_clean_results_and_never_resurrects_excluded_features(multi, empty):
    from apps.agent.geology_multi_review import update_map

    workflow, stage, _ = fixture_review(multi)
    workflow.plan["algorithms"]["geology-multi-apply"]["manifest"] = {
        "version": "1.0.5",
        "outputs": [{"key": "final_faults"}, {"key": "final_alterations"}],
    }
    stage["outputs"] = [
        {"key": "lithology", "kind": "vector", "resourceId": 101},
        {"key": "faults", "kind": "vector", "resourceId": 102},
        {"key": "alterations", "kind": "vector", "resourceId": 103},
        {"key": "changes_lithology_issues", "kind": "vector", "resourceId": 104},
    ]
    if not empty:
        stage["outputs"] += [
            {"key": "final_faults", "kind": "vector", "resourceId": 105},
            {"key": "final_alterations", "kind": "vector", "resourceId": 106},
        ]
    update_map(workflow)
    result = workflow.plan["multiElementMap"]
    assert result["after"]["lithology"] == 101
    assert result["changes"] == [104]
    if empty:
        assert "faults" not in result["after"] and "alterations" not in result
    else:
        assert result["after"]["faults"] == 105 and result["alterations"] == 106


def test_collect_hides_calculation_states_but_retains_downstream_inputs(
    multi, monkeypatch
):
    from apps.agent import demo_workflow
    from apps.compute.models import ComputeTask, ComputeOutput, ComputeImport

    workflow, stage, _ = fixture_review(multi)
    algorithm = AlgorithmResource.objects.create(
        identifier="geology-multi-apply", name="修正", created_by=multi["owner"]
    )
    manifest = {
        "outputs": [
            {"key": key}
            for key in ["faults", "alterations", "final_faults", "final_alterations"]
        ]
    }
    version = AlgorithmVersion.objects.create(
        algorithm=algorithm, version="1.0.5", checksum="a" * 64, manifest=manifest
    )
    task = ComputeTask.objects.create(
        owner=multi["owner"],
        name="成果集合验证",
        version=version,
        status="succeeded",
        idempotency_key="clean-collect",
        request_hash="a" * 64,
    )
    stage.update(
        results=[],
        manualApproved=True,
        status="running",
        taskId=str(task.id),
        bindings={},
    )
    workflow.plan["algorithms"]["geology-multi-apply"]["manifest"] = manifest
    workflow.status = "waiting_compute"
    workflow.save()
    resources = {}
    for key in ["faults", "alterations", "final_faults", "final_alterations"]:
        output = ComputeOutput.objects.create(
            task=task,
            key=key,
            label=key,
            kind="vector",
            file_name=key + ".gpkg",
            path=key + ".gpkg",
            size_bytes=1,
            checksum="b" * 64,
        )
        resource = DataResource.objects.create(
            name=key,
            code="collect-" + key,
            data_type="vector",
            source="compute-output:" + str(output.id),
        )
        ComputeImport.objects.create(
            output=output,
            requested_by=multi["owner"],
            name=key,
            status="ready",
            resource=resource,
        )
        resources[key] = resource
    monkeypatch.setattr(
        demo_workflow, "_authorize", lambda *args: (multi["owner"], multi["policy"])
    )
    monkeypatch.setattr(demo_workflow, "authorize_demo", lambda *args, **kwargs: None)
    assert demo_workflow._collect_stage(
        workflow, multi["owner"], multi["policy"], stage, task
    )
    for key in ("faults", "alterations"):
        resources[key].refresh_from_db()
        assert resources[key].source.startswith("workflow-working:")
        assert resources[key].owner_only
        assert resources[key].id not in workflow.result_resource_ids
        assert (
            next(item for item in stage["outputs"] if item["key"] == key)["resourceId"]
            == resources[key].id
        )
    assert set(workflow.result_resource_ids) == {
        resources[key].id for key in ("final_faults", "final_alterations")
    }


def test_mock_analysis_uses_current_issues_and_keeps_simulation_label(multi):
    from apps.agent.demo_decisions import _mock_decision

    wf, stage, results = fixture_review(multi)
    refs = [
        {"kind": "knowledge", "id": str(entry.id), "revision": entry.revision}
        for entry in multi["entries"]
    ]
    decision, edits = _mock_decision(
        SimpleNamespace(name="模拟测试"), stage, refs, results, wf
    )
    assert decision["modelMode"] == "mock"
    assert {edit["issue_id"] for edit in edits} == {"I0", "I1"}
    assert edits[1]["action"] == "downweight"
    assert edits[1]["weight"] > 0
    results[0]["rows"][0]["target_code"] = "T4"
    _, fresh = _mock_decision(
        SimpleNamespace(name="模拟测试"), stage, refs, results, wf
    )
    assert fresh[0]["target_code"] == "T4"


@pytest.mark.parametrize("action", ["geology-multi-apply", "request_review"])
def test_multi_model_protocol_distinguishes_proposal_from_insufficient_evidence(
    multi, settings, action
):
    from apps.agent.demo_decisions import decide

    settings.AGENT_MODELS = [
        {
            "alias": "mock",
            "name": "模型协议测试",
            "model_id": "qwen-fixture",
            "base_url": "http://127.0.0.1:19100/v1",
            "agent": True,
        }
    ]
    wf, stage, results = fixture_review(multi)
    proposal_edits = copy.deepcopy(stage.pop("edits"))
    stage.pop("decision")
    review_before = copy.deepcopy(wf.plan["modificationReview"])
    response = {
        "decision": {
            "problem": "核对当前检查结果与试用规则",
            "findings": ["实测对象已对应到本案例知识"],
            "judgement": "形成修改建议" if action.endswith("apply") else "需补充资料",
            "uncertainties": ["未批准前保持原对象"],
            "nextAction": action,
            "algorithmReason": "按当前测量与适用知识判断",
            "evidenceRefs": [
                {"kind": "output", "id": "2"},
                *[
                    {"kind": "knowledge", "id": str(entry.id)}
                    for entry in multi["entries"]
                ],
            ],
            "resultSummary": "建议需逐项批准"
            if action.endswith("apply")
            else "等待补证",
        },
        "edits": proposal_edits if action.endswith("apply") else [],
    }
    # A review may not carry executable proposals, even when its rows are valid.
    invalid = {**response, "edits": proposal_edits}
    raws = [invalid, response] if action == "request_review" else [response]
    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=800),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            side_effect=[iter([json.dumps(raw, ensure_ascii=False)]) for raw in raws],
        ) as stream,
    ):
        decision, edits = decide(
            wf, multi["owner"], multi["policy"], stage, results, lambda: None
        )
    assert decision["nextAction"] == action and decision["modelMode"] == "real"
    assert edits == response["edits"]
    instruction = stream.call_args_list[0].args[1][0]["content"]
    assert (
        "只有allowedAction和decision.nextAction均为geology-multi-apply" in instruction
    )
    assert "后端须等待用户逐项批准后才执行实际修改" in instruction
    assert "不能因建议尚待批准就把nextAction写成request_review" in instruction
    assert "request_review用于证据不足、冲突" in instruction
    assert "此时edits必须为[]" in instruction
    assert wf.plan["modificationReview"] == review_before
    assert not wf.plan["modificationReview"]["approvedSuggestionIds"]
    if action == "request_review":
        assert stream.call_count == 2
        assert "不得提前提交" in stage["modelAttempts"][0]["validationError"]
        assert not stage["modelAttempts"][0]["accepted"]
