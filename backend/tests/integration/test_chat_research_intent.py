"""Mock parser responses with real durable chat/workflow database records."""

import copy
import json
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.agent.demo_workflow import prepare_demo, authorize_demo
from apps.agent.models import AgentRun, AgentWorkflow, Conversation
from apps.agent.research_intents import process, serialize, history_compatible
from apps.agent.research_parser import plausible, validate
from apps.catalog.models import DataResource
from apps.compute.models import ComputeTask
from apps.compute.packages import ComputeError
from tests.integration.test_demo_workflow import demo  # noqa: F401
from tests.integration.test_compute import setup_compute  # noqa: F401

pytestmark = pytest.mark.django_db


def catalog(env):
    roles = ("early_image", "late_image", "valid_mask", "zones", "context")
    return {
        "scenarios": [
            {
                "scenario": "ecology_investigation",
                "available": True,
                "roleLabels": {role: role for role in roles},
                "sourceNote": "模拟测试资料",
                "inputs": {
                    role: [
                        {
                            "id": env["inputs"][role],
                            "name": role,
                            "sourceNote": "模拟测试资料",
                        }
                    ]
                    for role in roles
                },
                "parameterSpecs": [
                    {"key": "red", "label": "红光", "type": "band", "required": True},
                    {"key": "nir", "label": "近红外", "type": "band", "required": True},
                    {
                        "key": "early_date",
                        "label": "前期日期",
                        "type": "date",
                        "required": True,
                    },
                    {
                        "key": "late_date",
                        "label": "后期日期",
                        "type": "date",
                        "required": True,
                    },
                ],
                "algorithms": [
                    {"versionId": v.id}
                    for k, v in env["versions"].items()
                    if k in {"raster-ndvi", "ndvi-change", "ecology-priority"}
                ],
            }
        ]
    }


def parsed(env, action="start"):
    return {
        "action": action,
        "scenario": "ecology_investigation",
        "goal": "分析两期植被变化，选择调查优先区",
        "message": "已匹配模拟两期影像与调查资料",
        "inputs": {
            role: env["inputs"][role] for role in catalog(env)["scenarios"][0]["inputs"]
        },
        "parameters": {
            "red": 1,
            "nir": 2,
            "early_date": "2024-06-01",
            "late_date": "2025-06-01",
        },
        "questions": [],
    }


def run(
    env, prompt="请用NDVI分析两期影像植被变化并选出调查优先区", *, conversation=None
):
    conversation = conversation or Conversation.objects.create(
        owner=env["owner"], mode="agent"
    )
    return AgentRun.objects.create(
        conversation=conversation,
        owner=env["owner"],
        model="mock",
        prompt=prompt,
        idempotency_key="research-chat-" + str(conversation.runs.count()),
        status="succeeded",
        knowledge_selection={"mode": "none", "domains": []},
    )


def bridge(env, item, response):
    with (
        patch("apps.agent.research_presets.discover", return_value=catalog(env)),
        patch(
            "apps.agent.research_intents.interpret",
            return_value=(response, {"modelMode": "mock"}),
        ),
    ):
        return process(
            item, env["owner"], env["policy"], lambda: None, lambda *args: None
        )


def post(env, item, value, project=None):
    return env["client"].post(
        f"/api/agent/runs/{item.id}/research-intent/",
        json.dumps(value),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(project or env["project"].id),
    )


def test_multistep_ndvi_uses_model_bridge_before_single_operator(demo):  # noqa: F811
    from apps.agent.worker import run_task

    item = run(demo)
    item.status = "running"
    item.save()
    assert plausible(item, None)
    with (
        patch("apps.agent.worker.guard"),
        patch(
            "apps.agent.research_intents.process", return_value="真实科研任务已绑定"
        ) as research,
        patch("apps.agent.compute_intents.process") as single,
    ):
        run_task(item.id)
    research.assert_called_once()
    single.assert_not_called()
    item.refresh_from_db()
    assert item.status == "succeeded"


def test_single_ndvi_keeps_existing_fast_path(demo):  # noqa: F811
    item = run(demo, "计算NDVI，红光第1波段，近红外第2波段")
    assert not plausible(item, None)
    with patch("apps.agent.research_intents.interpret") as model:
        assert (
            process(
                item, demo["owner"], demo["policy"], lambda: None, lambda *args: None
            )
            is None
        )
    model.assert_not_called()


def test_workflow_creation_business_error_is_reported_in_chat(demo):  # noqa: F811
    from apps.agent.worker import run_task

    item = run(demo)
    item.status = "running"
    item.save()
    reason = "您已有活动科研工作流，请等待完成"
    with (
        patch("apps.agent.worker.guard"),
        patch(
            "apps.agent.research_intents.process",
            side_effect=ComputeError(reason, 409),
        ),
    ):
        run_task(item.id)
    item.refresh_from_db()
    assert item.status == "failed" and item.detail == reason
    assert item.events.filter(kind="status", text=reason).exists()
    assert not item.research_workflow_id


def test_unknown_failure_logs_code_location_without_private_error(demo, caplog):  # noqa: F811
    from apps.agent.worker import run_task

    item = run(demo)
    item.status = "running"
    item.save()
    private = "private-user-prompt path=C:/private/data.txt upstream-token=secret"
    with (
        patch("apps.agent.worker.guard"),
        patch("apps.agent.research_intents.process", side_effect=RuntimeError(private)),
    ):
        run_task(item.id)
    item.refresh_from_db()
    assert item.status == "failed"
    assert item.detail == "运行未能完成，请稍后重试或联系管理员"
    assert "RuntimeError" in caplog.text
    assert "apps.agent.worker.run_task:" in caplog.text
    assert private not in caplog.text
    assert "C:/private" not in caplog.text


def test_real_binding_initial_autoconfirm_and_idempotent_recovery(demo):  # noqa: F811
    item = run(demo)
    assert "开始" in bridge(demo, item, parsed(demo))
    item.refresh_from_db()
    workflow = item.research_workflow
    assert workflow.plan["chatExecution"]["requestRunId"] == item.id
    assert (
        workflow.plan["inputs"]["early_image"] != workflow.plan["inputs"]["late_image"]
    )
    assert serialize(item, demo["owner"], demo["policy"])["workflowId"] == str(
        workflow.id
    )
    assert "已开始" not in bridge(demo, item, parsed(demo))
    assert AgentWorkflow.objects.count() == 1
    prepare_demo(workflow, demo["owner"], demo["policy"])
    workflow.refresh_from_db()
    assert workflow.status == "queued" and workflow.execute_operators
    assert workflow.steps.filter(kind="chat_execution_authorized").exists()
    assert not ComputeTask.objects.exists()


def test_workflow_creation_and_chat_binding_roll_back_together(demo):  # noqa: F811
    from apps.agent.research_intents import _save

    item = run(demo)

    def fail_binding(current, value, workflow=None):
        if workflow is not None:
            raise RuntimeError("diagnostic binding failure")
        return _save(current, value)

    with (
        patch("apps.agent.research_intents._save", side_effect=fail_binding),
        pytest.raises(RuntimeError, match="binding failure"),
    ):
        bridge(demo, item, parsed(demo))
    item.refresh_from_db()
    assert item.research_workflow_id is None
    assert not AgentWorkflow.objects.exists()
    assert "_parserAudit" in item.research_intent
    assert "_initialExecutionAuthorization" not in item.research_intent


def test_text_clarification_reuses_goal_and_creates_one_workflow(demo):  # noqa: F811
    first = run(demo)
    question = parsed(demo, "clarify")
    question["parameters"].pop("nir")
    question["message"] = "请选择近红外波段"
    bridge(demo, first, question)
    first.refresh_from_db()
    assert first.research_intent["status"] == "clarifying"
    assert first.research_intent["questions"][0]["key"] == "nir"
    answer = run(demo, "近红外是2，开始执行", conversation=first.conversation)
    assert plausible(answer, first)
    bridge(demo, answer, parsed(demo))
    first.refresh_from_db()
    answer.refresh_from_db()
    assert answer.research_intent["originRunId"] == first.id
    assert first.research_workflow_id == answer.research_workflow_id
    bridge(demo, answer, parsed(demo))
    assert AgentWorkflow.objects.count() == 1


def test_button_answer_is_queued_once_and_respects_revision(demo):  # noqa: F811
    item = run(demo)
    question = parsed(demo, "clarify")
    question["parameters"].pop("nir")
    bridge(demo, item, question)
    item.refresh_from_db()
    value = {
        "action": "answer",
        "revision": item.research_intent["revision"],
        "answers": {"nir": "2"},
    }
    online = [{"alias": "mock", "status": "online", "contextWindowTokens": 32768}]
    with (
        patch("apps.agent.views.worker_online", return_value=True),
        patch("apps.agent.views.visible_models", return_value=online),
        patch("apps.agent.research_actions.visible_models", return_value=online),
    ):
        first = post(demo, item, value)
        second = post(demo, item, value)
    assert first.status_code == 202, first.content
    assert second.status_code == 202, second.content
    assert first.json()["id"] == second.json()["id"]
    child = AgentRun.objects.get(pk=first.json()["id"])
    assert (
        child.status == "queued"
        and child.research_intent["_resumeSourceRunId"] == item.id
    )
    bad = post(demo, item, {**value, "revision": "outdated", "answer": "另一个答案"})
    assert bad.status_code == 409


def test_explicit_user_bands_override_model_defaults(demo):  # noqa: F811
    item = run(demo, "请分析植被变化，红光波段=第3波段，近红外波段=第8波段")
    result = validate(parsed(demo), catalog(demo), item)
    assert result["parameters"]["red"] == 3 and result["parameters"]["nir"] == 8


def test_conflicting_bands_become_question(demo):  # noqa: F811
    item = run(demo, "分析植被变化，red=1 red=2 nir=2")
    result = validate(parsed(demo), catalog(demo), item)
    assert result["action"] == "clarify" and "red" not in result["parameters"]
    assert any(q["key"] == "red" for q in result["questions"])


def test_unlisted_role_resource_is_rejected(demo):  # noqa: F811
    value = parsed(demo)
    value["inputs"]["early_image"] = demo["inputs"]["initial_map"]
    with pytest.raises(ValidationError, match="未授权"):
        validate(value, catalog(demo), run(demo))


def test_manual_data_and_none_knowledge_do_not_leak_old_workflow(demo):  # noqa: F811
    first = run(demo)
    bridge(demo, first, parsed(demo))
    later = run(demo, "结果怎么样", conversation=first.conversation)
    later.resource_ids = [demo["inputs"]["early_image"]]
    assert not history_compatible(first, later)
    later.resource_ids = []
    workflow = first.research_workflow
    workflow.evidence = [{"id": 999, "domain": "arid_ecology"}]
    workflow.save()
    first.research_workflow = workflow
    assert not history_compatible(first, later)
    with patch("apps.agent.research_intents.interpret") as model:
        assert (
            process(
                later, demo["owner"], demo["policy"], lambda: None, lambda *args: None
            )
            is None
        )
    model.assert_not_called()


def test_revoked_private_resource_blocks_refresh_and_model(demo):  # noqa: F811
    item = run(demo)
    bridge(demo, item, parsed(demo))
    DataResource.objects.filter(pk=demo["inputs"]["early_image"]).update(
        owner_only=True, maintainer=demo["outsider"]
    )
    with pytest.raises(PermissionDenied):
        serialize(item, demo["owner"], demo["policy"])
    following = run(demo, "结果在哪", conversation=item.conversation)
    with (
        patch("apps.agent.research_intents.interpret") as model,
        pytest.raises(PermissionDenied),
    ):
        process(
            following, demo["owner"], demo["policy"], lambda: None, lambda *args: None
        )
    model.assert_not_called()


def test_cross_project_and_other_owner_answers_are_hidden(demo):  # noqa: F811
    item = run(demo)
    question = parsed(demo, "clarify")
    bridge(demo, item, question)
    value = {"action": "cancel", "revision": item.research_intent["revision"]}
    assert post(demo, item, value, demo["other_project"].id).status_code == 404
    demo["client"].force_login(demo["outsider"])
    assert post(demo, item, value).status_code == 404


@pytest.mark.parametrize("field", ["cancel_requested", "archived"])
def test_cancelled_source_cannot_autoconfirm(demo, field):  # noqa: F811
    item = run(demo)
    bridge(demo, item, parsed(demo))
    if field == "cancel_requested":
        item.cancel_requested = True
        item.save()
    else:
        item.conversation.archived = True
        item.conversation.save()
    with pytest.raises(PermissionDenied, match="授权"):
        prepare_demo(item.research_workflow, demo["owner"], demo["policy"])


def test_status_turn_cannot_invalidate_initial_authorization(demo):  # noqa: F811
    first = run(demo)
    bridge(demo, first, parsed(demo))
    token = copy.deepcopy(first.research_intent["_initialExecutionAuthorization"])
    progress = run(demo, "进度怎么样", conversation=first.conversation)
    bridge(demo, progress, parsed(demo, "status"))
    first.refresh_from_db()
    assert first.research_intent["_initialExecutionAuthorization"] == token
    prepare_demo(first.research_workflow, demo["owner"], demo["policy"])
    first.research_workflow.refresh_from_db()
    assert first.research_workflow.execute_operators


def test_quality_review_is_never_approved_automatically(demo):  # noqa: F811
    item = run(demo)
    bridge(demo, item, parsed(demo))
    workflow = item.research_workflow
    prepare_demo(workflow, demo["owner"], demo["policy"])
    workflow.refresh_from_db()
    workflow.plan.update(phase="review_results", reviewOutputs=[])
    workflow.status = "waiting_approval"
    workflow.save()
    following = run(demo, "继续跑吧", conversation=item.conversation)
    bridge(demo, following, parsed(demo, "status"))
    workflow.refresh_from_db()
    assert workflow.status == "waiting_approval"
    assert not workflow.steps.filter(kind="human_review").exists()


def test_frozen_chat_algorithm_ceiling_checked_on_each_stage(demo):  # noqa: F811
    item = run(demo)
    bridge(demo, item, parsed(demo))
    workflow = item.research_workflow
    prepare_demo(workflow, demo["owner"], demo["policy"])
    workflow.refresh_from_db()
    workflow.plan["chatExecution"]["algorithmSelectionMode"] = "manual"
    workflow.plan["chatExecution"]["selectedAlgorithmVersionIds"] = []
    with pytest.raises(PermissionDenied, match="明确选择"):
        authorize_demo(workflow, demo["owner"], demo["policy"])


def test_new_start_has_new_origin_not_previous_completed_origin(demo):  # noqa: F811
    first = run(demo)
    bridge(demo, first, parsed(demo))
    workflow = first.research_workflow
    workflow.status = "succeeded"
    workflow.save()
    rerun = run(demo, "请再次分析两期植被变化", conversation=first.conversation)
    bridge(demo, rerun, parsed(demo))
    assert rerun.research_intent["originRunId"] == rerun.id
    assert rerun.research_workflow_id != first.research_workflow_id
    assert AgentWorkflow.objects.count() == 2


def test_ecology_update_references_only_bound_completed_analysis(demo):  # noqa: F811
    first = run(demo)
    bridge(demo, first, parsed(demo))
    workflow = first.research_workflow
    workflow.status = "succeeded"
    workflow.save()
    updated = DataResource.objects.create(
        name="新增观测",
        code="context-updated",
        data_type="table",
        maintainer=demo["owner"],
    )
    later = run(demo, "补充新增观测并更新调查建议", conversation=first.conversation)
    response = parsed(demo, "update")
    response["inputs"]["context"] = updated.id
    candidates = catalog(demo)
    candidates["scenarios"][0]["inputs"]["context"].append(
        {
            "id": updated.id,
            "name": updated.name,
            "sourceNote": "模拟新增观测",
        }
    )
    with (
        patch("apps.agent.research_presets.discover", return_value=candidates),
        patch(
            "apps.agent.research_intents.interpret",
            return_value=(response, {"modelMode": "mock"}),
        ),
    ):
        process(later, demo["owner"], demo["policy"], lambda: None, lambda *args: None)
    assert later.research_workflow.plan["previousWorkflowId"] == str(workflow.id)
    assert later.research_workflow.plan["inputs"]["context"] == updated.id
    assert later.research_intent["originRunId"] == later.id


def test_parser_preserves_request_budget_and_strips_model_wrappers(demo):  # noqa: F811
    from apps.agent.research_parser import interpret

    item = run(demo)
    response = parsed(demo)
    requested, events = [], []
    wrapped = (
        "<think>内部内容不作为证据</think>\n```json\n" + json.dumps(response) + "\n```"
    )
    with (
        patch("apps.agent.provider.model_window", return_value=32768),
        patch(
            "apps.agent.context.count_tokens",
            return_value=256,
        ),
        patch("apps.agent.provider.stream", return_value=iter([wrapped])) as model,
    ):
        value, audit = interpret(
            item,
            demo["owner"],
            demo["policy"],
            catalog(demo),
            None,
            None,
            lambda: None,
            lambda *args: events.append(args),
            requested.append,
        )
    assert value == response and audit["inputTokens"] == 256
    assert requested[0]["request"]["userMessage"] == item.prompt
    assert "内部内容" not in json.dumps(audit, ensure_ascii=False)
    assert model.call_args.kwargs["structured"] is True
    assert model.call_args.args[2] == demo["policy"]["maxOutputTokens"]


def test_changed_input_after_parsing_cannot_autoconfirm(demo):  # noqa: F811
    item = run(demo)
    bridge(demo, item, parsed(demo))
    DataResource.objects.filter(pk=demo["inputs"]["early_image"]).update(
        name="解析后变更的影像",
        updated_at="2026-02-01T00:00:00Z",
    )
    with pytest.raises(PermissionDenied, match="授权"):
        prepare_demo(item.research_workflow, demo["owner"], demo["policy"])
