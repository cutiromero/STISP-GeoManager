"""History stays readable while ordinary model reuse follows current discovery."""

# ruff: noqa: F811

import json
import time
from uuid import uuid4

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied

from apps.agent.compute_intents import _selected, previous_plan
from apps.agent.models import AgentPolicy, AgentRun, AgentWorkflowStep, WorkflowUpload
from apps.agent.policy import default_policy
from apps.agent.selections import (
    check_history_evidence,
    context_reusable,
    history_compatible,
    knowledge_domains,
    sanitize_context_state,
)
from apps.agent.worker import context_messages, guard, run_task
from apps.catalog.models import DataResource
from apps.compute.packages import ComputeError
from apps.knowledge.domains import DOMAINS
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent  # noqa: F401
from tests.integration.test_agent_interactions import mock_model, question, respond

pytestmark = pytest.mark.django_db


def saved_run(env, prompt="独立说明", **values):
    return AgentRun.objects.create(
        conversation=env["conversation"],
        owner=env["user"],
        model="mock",
        prompt=prompt,
        status=values.pop("status", "succeeded"),
        idempotency_key=uuid4().hex,
        knowledge_selection=values.pop(
            "knowledge_selection", {"mode": "auto", "domains": [], "_contextRunIds": []}
        ),
        **values,
    )


def process_history(env):
    resource = DataResource.objects.create(
        name="后台过程材料",
        code="private-working-" + uuid4().hex,
        data_type="table",
        source="workflow-working:" + str(uuid4()),
        owner_only=True,
        maintainer=env["user"],
    )
    source = saved_run(
        env,
        "旧任务",
        answer="OLD_PROCESS_SECRET",
        evidence=[
            {
                "id": 1,
                "tool": "describe_resource",
                "resourceId": resource.id,
                "result": {"fields": [{"name": "private_field"}]},
            }
        ],
    )
    return source, resource


def suspended_state(env, source):
    return {
        "messages": [
            {"role": "user", "content": "旧任务"},
            {"role": "assistant", "content": source.answer},
            {"role": "user", "content": "本轮用户问题"},
            {"role": "assistant", "content": "本轮已调用工具"},
            {"role": "user", "content": "本轮真实工具返回"},
        ],
        "currentIndex": 2,
        "actions": 1,
        "corrections": 0,
        "phase": "model",
        "taskIds": [],
    }


def test_process_evidence_remains_readable_but_not_reused_by_new_run(setup_agent):  # noqa: F811
    env = setup_agent
    with project_scope(env["scope"]):
        source, _ = process_history(env)
        check_history_evidence(source, env["user"], default_policy())
        current = saved_run(env, status="running")
        assert not context_reusable(source, current, env["user"], default_policy())
        messages = context_messages(current, default_policy(), None)
        assert "OLD_PROCESS_SECRET" not in json.dumps(messages)
        guard(current.id, time.monotonic() + 30)
    response = env["client"].get(f"/api/agent/runs/{source.id}/", **env["header"])
    assert response.status_code == 200, response.content
    assert response.json()["run"]["answer"] == source.answer


def test_derived_process_summary_is_not_a_resource_free_escape(setup_agent):  # noqa: F811
    env = setup_agent
    with project_scope(env["scope"]):
        source, _ = process_history(env)
        summary = saved_run(
            env,
            "总结上轮",
            answer="DERIVED_PROCESS_SECRET",
            knowledge_selection={"_contextRunIds": [source.id]},
        )
        current = saved_run(env)
        messages = context_messages(current, default_policy(), None)
        text = json.dumps(messages)
        assert "OLD_PROCESS_SECRET" not in text and "DERIVED_PROCESS_SECRET" not in text
        assert not context_reusable(summary, current, env["user"], default_policy())
        check_history_evidence(summary, env["user"], default_policy())


def test_old_unproven_catalog_totals_are_requeried(setup_agent):  # noqa: F811
    env = setup_agent
    with project_scope(env["scope"]):
        source = saved_run(
            env,
            answer="旧目录包括300项过程资料",
            evidence=[
                {
                    "id": 1,
                    "resourceId": None,
                    "tool": "summarize_resource_catalog",
                    "result": {"total": 300, "complete": True},
                }
            ],
        )
        current = saved_run(env, "现在有哪些数据")
        assert not context_reusable(source, current, env["user"], default_policy())
        check_history_evidence(source, env["user"], default_policy())


def test_revoked_old_turn_does_not_block_a_new_run_guard(setup_agent):  # noqa: F811
    env = setup_agent
    with project_scope(env["scope"]):
        original = env["resource"]
        source = saved_run(
            env,
            answer="已撤权旧结论",
            evidence=[
                {
                    "id": 1,
                    "tool": "describe_resource",
                    "resourceId": original.id,
                    "result": {},
                }
            ],
        )
        DataResource.objects.filter(pk=original.id).update(
            owner_only=True, maintainer=env["other"]
        )
        current = saved_run(env, status="running")
        guard(current.id, time.monotonic() + 30)
        assert len(context_messages(current, default_policy(), None)) == 1
        with pytest.raises(PermissionDenied):
            check_history_evidence(source, env["user"], default_policy())


def test_manual_empty_data_does_not_fall_back_to_the_full_directory(setup_agent):
    env = setup_agent
    with project_scope(env["scope"]):
        source = saved_run(
            env,
            resource_ids=[env["resource"].id],
            compute_intent={
                "status": "collecting",
                "versionId": 7,
                "inputs": {"table": env["resource"].id},
            },
            evidence=[
                {
                    "id": 1,
                    "tool": "describe_resource",
                    "resourceId": env["resource"].id,
                    "result": {},
                }
            ],
        )
        current = saved_run(env, "继续处理这份资料", data_selection_mode="manual")
        check_history_evidence(source, env["user"], default_policy())
        assert not context_reusable(source, current, env["user"], default_policy())
        assert _selected(current) == []
        assert previous_plan(current) is None


def test_revoked_context_already_sent_to_the_model_stops_the_run(setup_agent):
    env = setup_agent
    with project_scope(env["scope"]):
        original = env["resource"]
        source = saved_run(
            env,
            evidence=[
                {
                    "id": 1,
                    "tool": "describe_resource",
                    "resourceId": original.id,
                    "result": {},
                }
            ],
        )
        current = saved_run(
            env,
            status="running",
            knowledge_selection={"_contextRunIds": [source.id]},
        )
        guard(current.id, time.monotonic() + 30)
        DataResource.objects.filter(pk=original.id).update(
            owner_only=True, maintainer=env["other"]
        )
        with pytest.raises(PermissionDenied):
            guard(current.id, time.monotonic() + 30)
        # Recovery may reach the sanitizer before sending another model request.
        guard(current.id, time.monotonic() + 30, include_context=False)


@pytest.mark.parametrize("with_marker", [True, False])
def test_resume_removes_old_prefix_and_keeps_same_run_tools(setup_agent, with_marker):  # noqa: F811
    env = setup_agent
    with project_scope(env["scope"]):
        source, _ = process_history(env)
        selected = {"mode": "auto", "domains": []}
        if with_marker:
            selected["_contextRunIds"] = [source.id]
        current = saved_run(
            env,
            execution_state=suspended_state(env, source),
            knowledge_selection=selected,
        )
        state = sanitize_context_state(current, env["user"], default_policy())
        assert state["currentIndex"] == 0 and state["actions"] == 1
        assert state["messages"] == current.execution_state["messages"][2:]
        assert current.knowledge_selection["_contextRunIds"] == []


def test_resume_worker_cannot_resend_saved_process_context(setup_agent, monkeypatch):  # noqa: F811
    env, captured = setup_agent, []
    with project_scope(env["scope"]):
        source, _ = process_history(env)
        current = saved_run(
            env,
            status="running",
            execution_state=suspended_state(env, source),
            knowledge_selection={"_contextRunIds": [source.id]},
        )
    mock_model(monkeypatch, [{"action": "final", "answer": "继续本轮核对。"}], captured)
    run_task(current.id)
    current.refresh_from_db()
    assert current.status == "succeeded", current.detail
    assert len(captured) == 1 and "OLD_PROCESS_SECRET" not in json.dumps(captured)
    assert "本轮真实工具返回" in json.dumps(captured, ensure_ascii=False)
    assert current.execution_state["actions"] == 1
    assert current.knowledge_selection["_contextRunIds"] == []


def test_answering_same_run_question_scrubs_only_old_context(setup_agent):  # noqa: F811
    env = setup_agent
    with project_scope(env["scope"]):
        source, _ = process_history(env)
        card = {
            **question(),
            "questionId": str(uuid4()),
            "revision": 1,
            "status": "pending",
        }
        current = saved_run(
            env,
            status="waiting_input",
            interaction=card,
            interaction_history=[card],
            execution_state=suspended_state(env, source),
            knowledge_selection={"_contextRunIds": [source.id]},
        )
    response, _ = respond(env, current)
    assert response.status_code == 202, response.content
    current.refresh_from_db()
    assert current.status == "queued" and current.execution_state["actions"] == 1
    rendered = json.dumps(current.execution_state, ensure_ascii=False)
    assert "OLD_PROCESS_SECRET" not in rendered and "本轮真实工具返回" in rendered
    assert current.interaction_history[0]["status"] == "answered"


def test_manual_algorithm_ceiling_also_filters_old_directory_ids(setup_agent):  # noqa: F811
    env = setup_agent
    with project_scope(env["scope"]):
        source = saved_run(
            env,
            evidence=[
                {
                    "id": 1,
                    "resourceId": None,
                    "tool": "list_compute_algorithms",
                    "result": {
                        "items": [{"id": 8, "versions": [{"id": 11}, {"id": 12}]}]
                    },
                }
            ],
        )
        current = saved_run(
            env, algorithm_selection_mode="manual", algorithm_version_ids=[11]
        )
        assert not history_compatible(source, current)
        current.algorithm_version_ids = [11, 12]
        assert history_compatible(source, current)
        check_history_evidence(source, env["user"], default_policy())


@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("如何整理实验记录", set(DOMAINS)),
        ("接着刚才的结论继续解释", {"geology"}),
        ("解释NDVI指标", {"remote_sensing", "arid_ecology"}),
    ],
)
def test_auto_knowledge_inherits_only_explicit_continuations(
    setup_agent, prompt, expected
):  # noqa: F811
    env = setup_agent
    with project_scope(env["scope"]):
        saved_run(env, "地质填图依据")
        current = saved_run(env, prompt)
        assert set(knowledge_domains(current)) == expected


def test_auto_continuation_keeps_server_resolved_domains(setup_agent):  # noqa: F811
    env = setup_agent
    with project_scope(env["scope"]):
        saved_run(
            env,
            "地质填图依据",
            knowledge_selection={"_resolvedDomains": ["geology", "remote_sensing"]},
        )
        continued = saved_run(env, "接着上轮说明")
        assert set(knowledge_domains(continued)) == {"geology", "remote_sensing"}
        fresh = saved_run(
            env, "独立知识说明", knowledge_selection={"_resolvedDomains": ["pipelines"]}
        )
        assert knowledge_domains(fresh, "矿物") == ["pipelines"]


def test_historical_pronouns_and_open_plans_ignore_process_inputs(setup_agent):  # noqa: F811
    env = setup_agent
    with project_scope(env["scope"]):
        source, resource = process_history(env)
        source.resource_ids = [resource.id]
        source.compute_intent = {
            "status": "collecting",
            "versionId": 7,
            "inputs": {"table": resource.id},
        }
        source.save(update_fields=["resource_ids", "compute_intent"])
        current = saved_run(env, "继续计算这份资料")
        assert _selected(current) == []
        assert previous_plan(current) is None


@pytest.fixture
def role_batch(setup_agent, settings, monkeypatch):
    from apps.agent import context, provider

    env = setup_agent
    env["project"].code = "02"
    env["project"].save(update_fields=["code"])
    env["user"].user_permissions.add(
        Permission.objects.get(codename="add_dataresource")
    )
    settings.AGENT_MODELS = [
        {**settings.AGENT_MODELS[0], "model_id": "profile-boundary"}
    ]
    AgentPolicy.objects.create(
        value={**default_policy(), "operatorEnabled": True, "maxOutputTokens": 512}
    )
    calls = []

    def stream(model, messages, maximum, guard, **options):
        calls.append(messages)
        if env.get("narrow_during_stream"):
            AgentRun.objects.filter(pk=env["role_run"].pk).update(
                resource_ids=[env["resource"].id]
            )
            options["monitor_guard"]()
        yield json.dumps(
            {
                "items": [
                    {
                        "uploadId": json.loads(messages[1]["content"])["items"][0][
                            "uploadId"
                        ],
                        "role": "units",
                        "reason": "填图单元表格",
                    }
                ]
            }
        )

    monkeypatch.setattr(provider, "stream", stream)
    monkeypatch.setattr(provider, "model_window", lambda model: 32768)
    monkeypatch.setattr(context, "count_tokens", lambda *args: 100)
    env["role_calls"] = calls
    return env


def role_attachment(env, *, source="catalog", selected="same", accessible=True):
    batch = uuid4().hex
    resource = DataResource.objects.create(
        name="本批单元表",
        code="roles-" + uuid4().hex,
        data_type="table",
        source="workflow-upload:" + batch if source == "upload" else "",
        owner_only=True,
        maintainer=env["user"] if accessible else env["other"],
    )
    upload = WorkflowUpload.objects.create(
        owner=env["user"],
        batch_id=batch,
        resource=resource,
        source=source,
        file_name="单元表.csv",
        profile={"kind": "table", "fields": [{"name": "name"}]},
    )
    selected_ids = (
        []
        if selected == "empty"
        else [resource.id if selected == "same" else env["resource"].id]
    )
    run = saved_run(
        env,
        status="running",
        data_selection_mode="manual",
        resource_ids=selected_ids,
        research_intent={"_uploadBatchId": batch},
    )
    env.update(role_run=run, role_upload=upload)
    return run, upload


@pytest.mark.parametrize("entrypoint", ["roles", "batch"])
@pytest.mark.parametrize(
    "source,selected,accessible,allowed",
    [
        ("catalog", "other", True, False),
        ("catalog", "same", True, True),
        ("upload", "other", True, True),
        ("upload", "other", False, False),
    ],
)
def test_role_batch_catalog_ceiling_and_real_upload_exception(
    role_batch, entrypoint, source, selected, accessible, allowed
):
    from apps.agent.generic_chat import validate_batch
    from apps.agent.workflow_roles import recognize_roles

    env = role_batch
    with project_scope(env["scope"]):
        run, upload = role_attachment(
            env, source=source, selected=selected, accessible=accessible
        )

        def invoke():
            if entrypoint == "batch":
                return validate_batch(
                    env["user"], run.conversation, upload.batch_id, run=run
                )
            return recognize_roles(
                env["user"],
                env["project"].id,
                upload.batch_id,
                "mock",
                source_run=run,
            )

        if allowed:
            result = invoke()
            if entrypoint == "roles":
                assert result["source"] == "model"
                assert len(env["role_calls"]) == 1
            else:
                assert [item.pk for item in result] == [upload.pk]
        else:
            error = PermissionDenied if accessible else ComputeError
            match = "已选择的数据范围" if accessible else "上传"
            with pytest.raises(error, match=match):
                invoke()
            assert env["role_calls"] == []
        assert not AgentWorkflowStep.objects.exists()


def test_role_catalog_selection_is_rechecked_during_the_model_stream(role_batch):
    from apps.agent.workflow_roles import recognize_roles

    env = role_batch
    with project_scope(env["scope"]):
        run, upload = role_attachment(env)
        env["narrow_during_stream"] = True
        with pytest.raises(PermissionDenied, match="已选择的数据范围"):
            recognize_roles(
                env["user"],
                env["project"].id,
                upload.batch_id,
                "mock",
                source_run=run,
            )
        assert len(env["role_calls"]) == 1
        assert not AgentWorkflowStep.objects.exists()
