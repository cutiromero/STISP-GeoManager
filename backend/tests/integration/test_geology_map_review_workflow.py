"""Real HTTP approval and durable evidence binding; algorithm runtime tested separately."""

# ruff: noqa: F811
import copy
import csv
import io
import json
from unittest.mock import patch

import pytest

from apps.agent.demo_decisions import validate_decision
from apps.agent.demo_results import EDIT_FIELDS, create_changes
from apps.agent.demo_workflow import (
    GRAPHS,
    advance_demo,
    confirm_demo,
    prepare_demo,
    _save,
)
from apps.agent.geology_review import (
    approved_edits,
    freeze_proposal,
    required_knowledge,
    validate_modifications,
)
from apps.agent.models import AgentWorkflow
from apps.agent.geology_input_validation import ROLES
from apps.agent.views import workflow_json
from apps.agent.workflow import step
from apps.catalog.models import DataResource
from apps.compute.models import (
    AlgorithmResource,
    AlgorithmVersion,
    ComputeTask,
    ComputeOutput,
)
from apps.compute.packages import ComputeError, checksum
from apps.core.storage import app_path, table_data_path
from apps.knowledge.models import KnowledgeEntry
from apps.knowledge.services import serialize
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def review_case(demo, monkeypatch):
    demo["inputs"]["coverage"] = DataResource.objects.create(
        name="完整制图范围",
        code="review-coverage",
        data_type="vector",
        maintainer=demo["owner"],
    ).id
    for _, identifier, bindings in GRAPHS["geology_map_review"]:
        if identifier in demo["versions"]:
            continue
        alg = AlgorithmResource.objects.create(
            identifier=identifier, name=identifier, created_by=demo["owner"]
        )
        demo["versions"][identifier] = AlgorithmVersion.objects.create(
            algorithm=alg,
            status="published",
            version="1.0.0",
            checksum="b" * 64,
            runtime_digest="sha256:" + "a" * 64,
            manifest={
                "inputs": [
                    {
                        "key": key,
                        "label": key,
                        "required": True,
                        "kind": "table" if key in {"rules", "changes"} else "vector",
                    }
                    for key in bindings
                ],
                "parameters": [],
                "outputs": [],
            },
        )
    monkeypatch.setattr(
        "apps.compute.data.candidate",
        lambda resource: {
            "id": resource.id,
            "fields": sorted(
                ROLES[
                    next(role for role in ROLES if demo["inputs"][role] == resource.id)
                ][2]
            ),
            "crs": "EPSG:4326",
            "geometryTypes": ["Polygon"] if resource.data_type == "vector" else [],
        },
    )
    inputs = {
        role: demo["inputs"][role] for role in ("initial_map", "coverage", "rules")
    }
    wf = AgentWorkflow.objects.create(
        owner=demo["owner"],
        model="mock",
        workflow_type="geology_map_review",
        goal="检查这张地质图，形成有依据的修正建议",
        max_iterations=12,
        max_operator_steps=16,
        resource_ids=list(set(inputs.values())),
        import_results=True,
        idempotency_key="map-review-case",
        plan={
            "inputs": inputs,
            "knowledgeSelection": {"mode": "manual", "domains": ["geology"]},
        },
    )
    prepare_demo(wf, demo["owner"], demo["policy"])
    demo["workflow"] = wf
    entries = [
        KnowledgeEntry.objects.create(
            seed_key=seed,
            title=title,
            statement=title + "应核对明确适用条件",
            status="published",
            domain="geology",
            sources=[{"title": "案例知识资料", "locator": "条目一"}],
        )
        for seed, title in (
            ("complete", "完整覆盖内部漏填"),
            ("babaoshan", "八宝山组地层时代"),
        )
    ]
    demo["entries"] = entries
    yield demo


def issue(row_id, kind, seed, **overrides):
    geom = {
        "type": "Polygon",
        "coordinates": [
            [[94, 35], [94.001, 35], [94.001, 35.001], [94, 35.001], [94, 35]]
        ],
    }
    return {
        "issue_id": row_id,
        "feature_id": "图斑-" + row_id,
        "kind": kind,
        "field": "class" if kind == "fill_gap" else "geologic_age",
        "old_value": "未分类" if kind == "fill_gap" else "J3",
        "new_value": "7" if kind == "fill_gap" else "T3",
        "rule_id": "规则-" + seed,
        "evidence_id": "条件-" + seed,
        "status": "repairable",
        "reason": "规则条件与数据对应",
        "input_checksum": "a" * 64,
        "area_m2": "100",
        "geometry_json": json.dumps(geom),
        "bounds_json": "[94,35,94.001,35.001]",
        "knowledge_seed": seed,
        **overrides,
    }


def waiting_suggestions(env):
    wf = env["workflow"]
    confirm_demo(wf, env["owner"], env["policy"], wf.plan_hash)
    # Freeze a completed real output file rather than borrowing a reference map.
    task = ComputeTask.objects.create(
        owner=env["owner"],
        version=env["versions"]["geology-map-check"],
        name="检查地图",
        status="succeeded",
        idempotency_key="check",
        request_hash="a",
    )
    step(wf, "submit_operator", compute_task_id=task.id)
    rows = [
        issue("漏填1", "fill_gap", "complete"),
        issue("时代2", "set_age", "babaoshan"),
    ]
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    path = app_path("outputs", str(task.id), "issues.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out.getvalue(), encoding="utf-8")
    output = ComputeOutput.objects.create(
        task=task,
        key="issues",
        label="发现的问题",
        kind="table",
        file_name="issues.csv",
        path=path.relative_to(app_path()).as_posix(),
        size_bytes=path.stat().st_size,
        checksum=checksum(path),
    )
    from apps.agent.demo_results import read_results

    results = read_results(wf, env["owner"], env["policy"], task)
    wf.plan["stages"][1].update(
        taskId=str(task.id), results=results, status="completed"
    )
    stage = wf.plan["stages"][2]
    wf.evidence = [serialize(entry) for entry in env["entries"]]
    stage.update(
        edits=[{key: row[key] for key in (*EDIT_FIELDS, "reason")} for row in rows],
        decision={
            "problem": "已发现两处疑点",
            "findings": ["条件与知识对应"],
            "judgement": "建议修正明确问题",
            "uncertainties": [],
            "nextAction": "geology-map-correct",
            "algorithmReason": "按已核对规则修改",
            "resultSummary": "提出建议，等待批准",
            "evidenceRefs": [
                {"kind": "knowledge", "id": str(entry.id)} for entry in env["entries"]
            ],
        },
    )
    wf.plan["stageIndex"] = 2
    freeze_proposal(wf, stage)
    _save(wf)
    return wf, stage, output


def confirm(env, wf, **body):
    return env["client"].post(
        f"/api/agent/workflows/{wf.id}/confirm/",
        json.dumps({"planHash": wf.plan_hash, **body}),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )


def test_prepare_does_not_search_or_authorize_editing(review_case):
    wf = review_case["workflow"]
    assert wf.evidence == [] and wf.plan["stageIndex"] == 0
    assert wf.plan["stages"][0]["identifier"] == "search_expert_knowledge"
    assert wf.status == "waiting_approval" and not ComputeTask.objects.exists()
    assert "modificationReview" not in workflow_json(wf)


def test_real_model_query_executes_actual_search_with_saved_revisions(
    review_case, settings
):
    env, wf = review_case, review_case["workflow"]
    settings.AGENT_MODELS[0] = {
        **settings.AGENT_MODELS[0],
        "model_id": "qwen-provider-test",
    }
    confirm_demo(wf, env["owner"], env["policy"], wf.plan_hash)
    value = {
        "decision": {
            "problem": wf.goal,
            "findings": ["输入范围要求完整覆盖"],
            "judgement": "先检索完整覆盖和地层时代知识",
            "uncertainties": [],
            "nextAction": "search_expert_knowledge",
            "algorithmReason": "先查依据再检查",
            "evidenceRefs": [
                {"kind": "resource", "id": str(env["inputs"]["initial_map"])}
            ],
            "resultSummary": "查阅专家知识",
            "knowledgeQuery": "完整覆盖 漏填 八宝山组 地层时代",
        },
        "edits": [],
    }
    with (
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=700),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            return_value=iter([json.dumps(value)]),
        ) as stream,
    ):
        advance_demo(wf.id)
    wf.refresh_from_db()
    assert wf.status == "queued", wf.detail
    assert wf.plan["stageIndex"] == 1 and len(wf.evidence) == 2
    assert wf.plan["actualModelCallCount"] == 1
    assert stream.call_count == 1 and not ComputeTask.objects.exists()
    payload = json.loads(stream.call_args.args[1][1]["content"])
    assert payload["inputRoles"][0]["metadata"]["fields"] == sorted(
        ROLES["initial_map"][2]
    )
    record = wf.steps.get(kind="search_expert_knowledge")
    assert record.action["query"] == value["decision"]["knowledgeQuery"]
    assert {(v["id"], v["revision"]) for v in record.output_refs["knowledge"]} == {
        (entry.id, entry.revision) for entry in env["entries"]
    }


def test_approve_subset_is_frozen_and_only_selected_rows_reach_changes_file(
    review_case,
):
    wf, stage, _ = waiting_suggestions(review_case)
    initial_hash = wf.plan_hash
    ids = [item["id"] for item in wf.plan["modificationReview"]["suggestions"]]
    response = confirm(review_case, wf, selectedSuggestionIds=[ids[0]])
    assert response.status_code == 200, response.content
    wf.refresh_from_db()
    assert (
        wf.status == "queued"
        and wf.plan["modificationReview"]["approvedSuggestionIds"] == ids[:1]
    )
    stage = wf.plan["stages"][2]
    edits = approved_edits(wf, review_case["owner"], review_case["policy"], stage)
    assert len(edits) == 1 and edits[0]["feature_id"] == "图斑-漏填1"
    resource = create_changes(
        wf,
        review_case["owner"],
        review_case["policy"],
        edits,
        wf.plan["stages"][1]["results"],
    )
    text = table_data_path(resource.storage_path.removeprefix("table/")).read_text()
    assert "图斑-漏填1" in text and "图斑-时代2" not in text
    assert "issue_id,kind" in text
    approval = wf.steps.get(kind="modifications_approved")
    assert approval.action["planHash"] == initial_hash
    saved = (
        review_case["client"]
        .get(
            f"/api/agent/workflows/{wf.id}/",
            HTTP_X_PROJECT_ID=str(review_case["project"].id),
        )
        .json()
    )
    assert saved["modificationReview"]["approvedSuggestionIds"] == ids[:1]
    assert not ComputeTask.objects.filter(
        version__algorithm__identifier="geology-map-correct"
    ).exists()


def test_model_geometry_projection_does_not_change_approval_or_execution(review_case):
    from apps.agent.demo_decisions import decision_payload
    from apps.agent.geology_review import proposal

    wf, stage, _ = waiting_suggestions(review_case)
    results = wf.plan["stages"][1]["results"]
    saved_plan, saved_results = copy.deepcopy(wf.plan), copy.deepcopy(results)
    expected_review, expected_rows = proposal(wf, stage, results)
    payload = decision_payload(wf, stage, [], results)
    assert "geometry_json" not in payload["actualResults"][0]["rows"][0]
    assert "preview" not in payload["modificationReview"]["suggestions"][0]
    assert (wf.plan, results) == (saved_plan, saved_results)
    assert proposal(wf, stage, results) == (expected_review, expected_rows)
    selected = [expected_review["suggestions"][0]["id"]]
    response = confirm(review_case, wf, selectedSuggestionIds=selected)
    assert response.status_code == 200, response.content
    wf.refresh_from_db()
    restored = wf.plan["stages"][2]
    actual = approved_edits(wf, review_case["owner"], review_case["policy"], restored)
    assert actual == [{key: expected_rows[0][key] for key in (*EDIT_FIELDS, "reason")}]
    assert (
        wf.plan["modificationReview"]["suggestions"] == expected_review["suggestions"]
    )
    assert "preview" in wf.plan["modificationReview"]["suggestions"][0]


@pytest.mark.parametrize("ids", [None, [], ["stale"], ["duplicate", "duplicate"]])
def test_empty_unknown_and_duplicate_approval_do_not_edit(review_case, ids):
    wf, _, _ = waiting_suggestions(review_case)
    count = DataResource.objects.count()
    assert confirm(review_case, wf, selectedSuggestionIds=ids).status_code in {400, 409}
    wf.refresh_from_db()
    assert wf.status == "waiting_approval" and DataResource.objects.count() == count
    assert not wf.steps.filter(kind="modifications_approved").exists()


def test_rejection_keeps_original_file_and_zero_edit_tasks(review_case):
    wf, _, output = waiting_suggestions(review_case)
    before = app_path(output.path).read_bytes()
    response = confirm(review_case, wf, decision="reject", feedback="先补充资料再决定")
    assert response.status_code == 200, response.content
    wf.refresh_from_db()
    advance_demo(wf.id)
    assert wf.status == "cancelled" and app_path(output.path).read_bytes() == before
    assert wf.plan["modificationReview"]["approvedSuggestionIds"] == []
    assert not DataResource.objects.filter(source=f"demo-changes:{wf.id}").exists()
    assert ComputeTask.objects.count() == 1


@pytest.mark.parametrize(
    "changed", ["output", "proposal", "input", "knowledge", "hash"]
)
def test_changed_evidence_or_plan_blocks_approval(review_case, changed):
    wf, stage, output = waiting_suggestions(review_case)
    identity = wf.plan["modificationReview"]["suggestions"][0]["id"]
    if changed == "output":
        app_path(output.path).write_text("changed", encoding="utf-8")
    elif changed == "proposal":
        stage["edits"][0]["reason"] = "其他理由"
        _save(wf)
    elif changed == "input":
        resource = DataResource.objects.get(pk=wf.plan["inputs"]["coverage"])
        resource.description = "覆盖范围变更"
        resource.save()
    elif changed == "knowledge":
        KnowledgeEntry.objects.filter(pk=review_case["entries"][0].id).update(
            revision=2
        )
    elif changed == "hash":
        wf.plan["stages"][2]["parameters"] = {"changed": True}
        wf.save(update_fields=["plan"])
    response = confirm(review_case, wf, selectedSuggestionIds=[identity])
    assert response.status_code in {400, 403, 409}, response.content
    assert not wf.steps.filter(kind="modifications_approved").exists()


def test_approved_scope_cannot_be_expanded_or_faked(review_case):
    wf, _, _ = waiting_suggestions(review_case)
    ids = [item["id"] for item in wf.plan["modificationReview"]["suggestions"]]
    assert confirm(review_case, wf, selectedSuggestionIds=ids[:1]).status_code == 200
    wf.refresh_from_db()
    stage = wf.plan["stages"][2]
    stage["approvedEdits"].append(stage["proposedEdits"][1])
    with pytest.raises(ComputeError, match="当前范围"):
        approved_edits(wf, review_case["owner"], review_case["policy"], stage)


def test_approved_subset_submits_only_actual_frozen_operations(review_case):
    wf, _, _ = waiting_suggestions(review_case)
    selected = [wf.plan["modificationReview"]["suggestions"][1]["id"]]
    assert confirm(review_case, wf, selectedSuggestionIds=selected).status_code == 200
    advance_demo(wf.id)
    wf.refresh_from_db()
    assert wf.status == "waiting_compute", wf.detail
    task = ComputeTask.objects.get(pk=wf.plan["stages"][2]["taskId"])
    assert task.version.algorithm.identifier == "geology-map-correct"
    changes = task.input_records.get(key="changes").resource
    data = list(
        csv.DictReader(
            io.StringIO(
                table_data_path(changes.storage_path.removeprefix("table/")).read_text()
            )
        )
    )
    assert len(data) == 1 and data[0]["kind"] == "set_age"
    assert (
        data[0]["feature_id"] == "图斑-时代2" and data[0]["input_checksum"] == "a" * 64
    )


def test_changed_execution_parameters_need_new_approval(review_case):
    wf, _, _ = waiting_suggestions(review_case)
    selected = [wf.plan["modificationReview"]["suggestions"][0]["id"]]
    assert confirm(review_case, wf, selectedSuggestionIds=selected).status_code == 200
    wf.refresh_from_db()
    stage = wf.plan["stages"][2]
    stage["parameters"]["unexpected"] = True
    _save(wf)
    advance_demo(wf.id)
    wf.refresh_from_db()
    assert wf.status == "failed" and "当前范围" in wf.detail
    assert ComputeTask.objects.count() == 1


def test_suggestion_requires_the_actual_matching_knowledge_and_valid_preview(
    review_case,
):
    wf, stage, _ = waiting_suggestions(review_case)
    original = copy.deepcopy(stage["decision"])
    stage["decision"]["evidenceRefs"] = stage["decision"]["evidenceRefs"][1:]
    with pytest.raises(ComputeError, match="对应规则"):
        freeze_proposal(wf, stage)
    stage["decision"] = original
    wf.plan["stages"][1]["results"][0]["rows"][0]["geometry_json"] = "{}"
    with pytest.raises(ComputeError, match="修改范围"):
        freeze_proposal(wf, stage)


def test_knowledge_query_not_allowed_in_ordinary_stage():
    value = {
        "problem": "检查",
        "findings": [],
        "judgement": "继续",
        "uncertainties": [],
        "nextAction": "geology-map-check",
        "algorithmReason": "核对",
        "resultSummary": "",
        "evidenceRefs": [{"kind": "resource", "id": "1"}],
        "knowledgeQuery": "地层",
    }
    with pytest.raises(ComputeError, match="未声明"):
        validate_decision(value, [{"kind": "resource", "id": "1"}], "geology-map-check")


@pytest.mark.parametrize(
    "changed",
    [
        {"new_value": "错误"},
        {"status": "needs_review"},
        {"kind": "move_boundary"},
        {"input_checksum": "invalid"},
    ],
)
def test_model_edit_must_match_actual_repairable_issue(changed):
    row = issue("位置可变", "fill_gap", "complete")
    edits = [{key: row[key] for key in (*EDIT_FIELDS, "reason")}]
    row.update(changed)
    with pytest.raises(ComputeError):
        validate_modifications(edits, [{"rows": [row]}])


def test_each_issue_exposes_only_retrieved_current_matching_knowledge(review_case):
    env = review_case
    wf, _, output = waiting_suggestions(env)
    results = wf.plan["stages"][1]["results"]
    requirements = required_knowledge(wf, results)
    assert [item["outputId"] for item in requirements] == [output.id, output.id]
    assert [item["rowIndex"] for item in requirements] == [0, 1]
    assert [item["requiredKnowledgeRefs"][0]["id"] for item in requirements] == [
        entry.id for entry in env["entries"]
    ]
    assert all(item["knowledgeState"] == "available" for item in requirements)
    wf.evidence = wf.evidence[:1]
    requirements = required_knowledge(wf, results)
    assert requirements[1]["requiredKnowledgeRefs"] == []
    assert requirements[1]["knowledgeState"] == "not_retrieved"
    env["entries"][0].revision += 1
    env["entries"][0].save()
    assert required_knowledge(wf, results)[0]["requiredKnowledgeRefs"] == []


@pytest.mark.parametrize(
    "binding,accepted",
    [
        ("explicit", True),
        ("id_only", True),
        ("revision_only", True),
        ("empty", True),
        ("wrong_id", False),
        ("missing_id", False),
        ("stale_revision", False),
    ],
)
def test_explicit_issue_knowledge_binding_cannot_fall_back_to_seed(
    review_case, binding, accepted
):
    env = review_case
    wf, stage, _ = waiting_suggestions(env)
    results = wf.plan["stages"][1]["results"]
    row, entry = results[0]["rows"][0], env["entries"][0]
    row.update(knowledge_id=str(entry.id), knowledge_revision=str(entry.revision))
    if binding == "id_only":
        row["knowledge_revision"] = ""
    elif binding == "revision_only":
        row["knowledge_id"] = ""
    elif binding == "empty":
        row.update(knowledge_id="", knowledge_revision="")
    elif binding == "wrong_id":
        row["knowledge_id"] = str(env["entries"][1].id)
    elif binding == "missing_id":
        row["knowledge_id"] = "99999999"
    elif binding == "stale_revision":
        entry.revision += 1
        entry.save()
        wf.evidence[0] = serialize(entry)
    requirement = required_knowledge(wf, results)[0]
    if accepted:
        assert requirement["requiredKnowledgeRefs"] == [
            {
                "id": entry.id,
                "revision": entry.revision,
                "title": entry.title,
            }
        ]
        freeze_proposal(wf, stage)
        assert (
            wf.plan["modificationReview"]["suggestions"][0]["knowledgeRefs"]
            == requirement["requiredKnowledgeRefs"]
        )
    else:
        assert requirement["requiredKnowledgeRefs"] == []
        assert requirement["knowledgeState"] == "not_retrieved"
        with pytest.raises(ComputeError, match="对应规则"):
            freeze_proposal(wf, stage)
    assert ComputeTask.objects.count() == 1


@pytest.mark.parametrize("change", [{"status": "draft"}, {"domain": "pipelines"}])
def test_issue_knowledge_locators_keep_visibility_and_domain_boundaries(
    review_case, change
):
    env = review_case
    wf, _, _ = waiting_suggestions(env)
    KnowledgeEntry.objects.filter(pk=env["entries"][0].id).update(**change)
    result = required_knowledge(wf, wf.plan["stages"][1]["results"])
    assert result[0]["requiredKnowledgeRefs"] == []
    assert result[1]["requiredKnowledgeRefs"][0]["id"] == env["entries"][1].id


def model_proposal_case(env, settings):
    wf, stage, output = waiting_suggestions(env)
    settings.AGENT_MODELS[0] = {
        **settings.AGENT_MODELS[0],
        "model_id": "qwen-provider-test",
    }
    value = {
        "decision": stage.pop("decision"),
        "edits": stage.pop("edits"),
    }
    value["decision"]["evidenceRefs"].append({"kind": "output", "id": str(output.id)})
    wf.plan.pop("modificationReview")
    stage.pop("proposedEdits")
    stage["status"] = "pending"
    wf.status, wf.plan["phase"] = "queued", "decide"
    _save(wf)
    return wf, value


def model_responses(responses, messages):
    values = iter(responses)

    def stream(model, request, output, guard, **options):
        messages.append(copy.deepcopy(request))
        return iter([json.dumps(next(values), ensure_ascii=False)])

    return stream


@pytest.mark.parametrize("remain_wrong", [False, True])
def test_model_must_correct_each_citation_itself_with_one_shared_budget_retry(
    review_case, settings, remain_wrong
):
    env = review_case
    wf, correct = model_proposal_case(env, settings)
    wrong = copy.deepcopy(correct)
    wrong["decision"]["evidenceRefs"] = [
        ref
        for ref in wrong["decision"]["evidenceRefs"]
        if ref["id"] != str(env["entries"][1].id) or ref["kind"] != "knowledge"
    ]
    messages = []
    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=700),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            side_effect=model_responses(
                [wrong, wrong if remain_wrong else correct], messages
            ),
        ),
    ):
        advance_demo(wf.id)
    wf.refresh_from_db()
    assert len(messages) == wf.plan["actualModelCallCount"] == 2
    assert ComputeTask.objects.count() == 1
    feedback = json.loads(messages[1][-1]["content"])
    assert "对应规则" in feedback["validationError"]
    requirements = feedback["editTask"]["issueKnowledgeRequirements"]
    assert requirements[1]["requiredKnowledgeRefs"][0]["id"] == env["entries"][1].id
    assert "不会补入引用" in feedback["knowledgeCitationInstruction"]
    assert json.loads(messages[1][-2]["content"]) == wrong
    if remain_wrong:
        assert wf.status == "failed" and "对应规则" in wf.detail
        assert "modificationReview" not in wf.plan
    else:
        assert wf.status == "waiting_approval"
        assert len(wf.plan["modificationReview"]["suggestions"]) == 2
        assert wf.plan["modificationReview"]["approvedSuggestionIds"] == []
        assert wf.plan["stages"][2]["edits"] == correct["edits"]


def test_model_citation_retry_cannot_exceed_existing_shared_request_budget(
    review_case, settings
):
    wf, wrong = model_proposal_case(review_case, settings)
    wrong["decision"]["evidenceRefs"] = [
        ref for ref in wrong["decision"]["evidenceRefs"] if ref["kind"] != "knowledge"
    ]
    wf.plan["actualModelCallCount"] = wf.max_iterations - 1
    _save(wf)
    messages = []
    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=700),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            side_effect=model_responses([wrong], messages),
        ),
    ):
        advance_demo(wf.id)
    wf.refresh_from_db()
    assert len(messages) == 1
    assert wf.plan["actualModelCallCount"] == wf.max_iterations
    assert wf.status == "failed" and wf.plan["phase"] == "budget_exhausted"
    summary = wf.plan["budgetExhausted"]
    assert summary["usedRequests"] == summary["limit"] == wf.max_iterations
    assert summary["minimumRemainingRequests"] == 3
    attempts = wf.plan["stages"][wf.plan["stageIndex"]]["modelAttempts"]
    assert len(attempts) == 2
    assert attempts[0]["requested"] is True and attempts[0]["status"] == "rejected"
    assert attempts[1]["requested"] is False
    assert attempts[1]["status"] == "budget_blocked"
    assert "调整并重新发起" in wf.detail
    assert ComputeTask.objects.count() == 1


def test_missing_rule_knowledge_requires_model_review_instead_of_silent_edit(
    review_case, settings
):
    wf, unsupported = model_proposal_case(review_case, settings)
    wf.evidence = wf.evidence[:1]
    _save(wf)
    unsupported["decision"]["evidenceRefs"] = [
        ref
        for ref in unsupported["decision"]["evidenceRefs"]
        if ref["kind"] != "knowledge" or ref["id"] == str(wf.evidence[0]["id"])
    ]
    review = copy.deepcopy(unsupported)
    review["decision"].update(
        nextAction="request_review", judgement="缺少对应时代知识，请补查后再形成建议"
    )
    review["edits"] = []
    messages = []
    with (
        patch("apps.agent.demo_decisions.resource_context", return_value=[]),
        patch("apps.agent.demo_decisions.provider.model_window", return_value=32768),
        patch("apps.agent.context.count_tokens", return_value=700),
        patch(
            "apps.agent.demo_decisions.provider.stream",
            side_effect=model_responses([unsupported, review], messages),
        ),
    ):
        advance_demo(wf.id)
    wf.refresh_from_db()
    assert wf.status == "waiting_approval" and wf.plan["phase"] == "review_results"
    assert "modificationReview" not in wf.plan and ComputeTask.objects.count() == 1
    feedback = json.loads(messages[1][-1]["content"])
    missing = feedback["editTask"]["issueKnowledgeRequirements"][1]
    assert missing["knowledgeState"] == "not_retrieved"
    assert missing["requiredKnowledgeRefs"] == []
    assert wf.plan["actualModelCallCount"] == 2
