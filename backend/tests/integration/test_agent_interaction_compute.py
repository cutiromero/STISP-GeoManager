"""Interaction/compute integration; model responses are automation fixtures.

These tests submit real task rows and read real raster files. Production
acceptance separately exercises the configured model and isolated worker.
"""
# ruff: noqa: F811 - pytest fixture dependencies are imported by name.

import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from apps.agent.compute_tools import resume_followups
from apps.agent.interactions import resume_compute
from apps.agent.models import AgentRun
from apps.agent.tools import execute
from apps.agent.worker import claim, run_task
from apps.compute.data import inspect_output
from apps.compute.models import ComputeTask, ComputeOutput
from apps.compute.packages import checksum
from apps.core.storage import app_path
from tests.integration.test_agent_compute_intent import env as raster_env  # noqa: F401
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_agent_interactions import mock_model


def make_run(env, prompt="计算这张影像的NDVI"):
    return AgentRun.objects.create(
        conversation=env["conversation"],
        owner=env["owner"],
        model="mock",
        prompt=prompt,
        resource_ids=[env["raster"].id],
        status="running",
        idempotency_key="interactive-ndvi",
    )


def band_question(reason="影像实际有8个波段，但尚未提供红光和近红外对应波段"):
    options = [{"value": str(i), "label": f"第{i}波段"} for i in range(1, 9)]
    return {
        "action": "ask_user",
        "arguments": {
            "kind": "input",
            "title": "确认NDVI的两个波段",
            "reason": reason,
            "questions": [
                {
                    "key": key,
                    "label": label,
                    "type": "single",
                    "required": True,
                    "options": options,
                }
                for key, label in [("red", "红光波段"), ("nir", "近红外波段")]
            ],
        },
    }


def submit_answer(env, run, **changes):
    run.refresh_from_db()
    value = {
        "action": "answer",
        "questionId": run.interaction["questionId"],
        "revision": run.interaction["revision"],
        "submissionKey": "bands-answer-once",
        "answers": {"red": "3", "nir": "8"},
        **changes,
    }
    return env["client"].post(
        f"/api/agent/runs/{run.id}/interaction/",
        json.dumps(value),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )


def run_command(env, red=3, nir=8):
    return {
        "action": "execute_operator",
        "arguments": {
            "versionId": env["ndvi"].id,
            "inputs": {"image": env["raster"].id},
            "parameters": {"red": red, "nir": nir},
        },
    }


def raster_output(task):
    path = app_path("interaction-tests", str(task.id), "ndvi.tif")
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=1,
        dtype="float32",
        crs="EPSG:32645",
        transform=from_origin(615000, 4440000, 10, 10),
    ) as target:
        target.write(np.zeros((1, 4, 4), dtype="float32"))
    output = ComputeOutput.objects.create(
        task=task,
        key="ndvi",
        label="NDVI结果",
        kind="raster",
        file_name="ndvi.tif",
        path=path.relative_to(app_path()).as_posix(),
        size_bytes=path.stat().st_size,
        checksum=checksum(path),
        metadata=inspect_output(path, "raster"),
    )
    task.status = "succeeded"
    task.save(update_fields=["status"])
    return output


def test_missing_bands_answer_submits_once_then_reads_real_output(
    raster_env, monkeypatch
):
    env = raster_env
    run = make_run(env)
    mock_model(
        monkeypatch,
        [
            {
                "action": "describe_resource",
                "arguments": {"resourceId": env["raster"].id},
            },
            {"action": "list_compute_algorithms", "arguments": {"query": "NDVI"}},
            band_question(),
        ],
    )
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "waiting_input" and not ComputeTask.objects.exists()
    assert submit_answer(env, run).status_code == 202
    assert submit_answer(env, run).status_code == 202
    assert claim() == run.id
    mock_model(monkeypatch, [run_command(env)])
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "waiting_compute"
    task = ComputeTask.objects.get()
    assert task.parameters == {"red": 3, "nir": 8}
    resume_compute()
    run.refresh_from_db()
    assert run.status == "waiting_compute" and claim() is None
    output = raster_output(task)
    resume_followups()
    resume_compute()
    resume_compute()  # Duplicate polling cannot duplicate continuation.
    run.refresh_from_db()
    assert run.status == "queued" and run.execution_state["outputIds"] == [output.id]
    assert sum(ev["tool"] == "get_compute_task" for ev in run.evidence) == 1
    assert claim() == run.id
    captured = []
    mock_model(
        monkeypatch,
        [
            {"action": "read_compute_output", "arguments": {"outputId": output.id}},
            {
                "action": "final",
                "answer": "按您补充的红光3、近红外8计算，实际结果为单波段指数，近似统计均值为0；需辅助观测判断生态原因。",
            },
        ],
        captured,
    )
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "succeeded" and ComputeTask.objects.count() == 1
    read = next(
        ev["result"] for ev in run.evidence if ev["tool"] == "read_compute_output"
    )
    assert read["checkedChecksum"] == output.checksum and read["bands"][0]["mean"] == 0
    assert "按您补充" in run.answer  # Platform status must not erase interpretation.
    assert run.interaction_history[0]["status"] == "answered"
    assert str(output.id) in json.dumps(captured, ensure_ascii=False)


def test_out_of_range_uses_actual_evidence_and_corrected_answer(
    raster_env, monkeypatch
):
    env = raster_env
    run = make_run(env, "计算NDVI，red=9 nir=8")
    captured = []
    mock_model(
        monkeypatch,
        [
            run_command(env, red=9),
            band_question("实际影像只有8个波段，red=9超出1至8范围"),
        ],
        captured,
    )
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "waiting_input" and not ComputeTask.objects.exists()
    assert "只有8个波段" in json.dumps(captured[-1], ensure_ascii=False)
    assert submit_answer(env, run).status_code == 202
    assert claim() == run.id
    mock_model(monkeypatch, [run_command(env)])
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "waiting_compute"
    assert ComputeTask.objects.get().parameters == {"red": 3, "nir": 8}


def test_cancel_compute_stops_continuation_and_reports_real_state(
    raster_env, monkeypatch
):
    env = raster_env
    run = make_run(env, "计算NDVI，red=3 nir=8")
    mock_model(monkeypatch, [run_command(env)])
    run_task(run.id)
    task = ComputeTask.objects.get()
    response = env["client"].post(
        f"/api/agent/runs/{run.id}/cancel/", HTTP_X_PROJECT_ID=str(env["project"].id)
    )
    assert response.status_code == 200
    assert "已提交计算可能继续" in response.json()["detail"]
    raster_output(task)
    resume_compute()
    run.refresh_from_db()
    assert run.status == "cancelled" and claim() is None
    assert not run.events.filter(kind="continuation").exists()


def test_result_reading_checks_checksum_and_current_project(raster_env, monkeypatch):
    env = raster_env
    run = make_run(env, "计算NDVI，red=3 nir=8")
    mock_model(monkeypatch, [run_command(env)])
    run_task(run.id)
    output = raster_output(ComputeTask.objects.get())
    app_path(output.path).write_bytes(b"changed")
    from apps.compute.packages import ComputeError

    with pytest.raises(ComputeError, match="内容已变化"):
        execute(run, "read_compute_output", {"outputId": output.id})


@pytest.mark.parametrize(
    "identifier", ["geology-edit", "geology-age-edit", "geology-map-correct"]
)
def test_geology_editing_cannot_bypass_existing_approval(raster_env, identifier):
    from django.core.exceptions import PermissionDenied
    from apps.projects.context import ProjectScope, project_scope

    env = raster_env
    version = env["ndvi"]
    with project_scope(ProjectScope((1,), 1, env["admin"].id, True)):
        version.algorithm.identifier = identifier
        version.algorithm.save(update_fields=["identifier"])
    run = make_run(env)
    with pytest.raises(PermissionDenied, match="逐项方案审批"):
        execute(run, "execute_operator", run_command(env)["arguments"])
    assert not ComputeTask.objects.exists()


@pytest.mark.parametrize("next_algorithm", ["ndvi", "ndwi"])
def test_same_run_changes_parameters_or_algorithm_after_result_and_answer(
    raster_env, monkeypatch, next_algorithm
):
    env = raster_env
    run = make_run(env, "计算NDVI，red=3 nir=8，然后根据结果继续分析")
    mock_model(monkeypatch, [run_command(env)])
    run_task(run.id)
    first = ComputeTask.objects.get()
    initial_output = raster_output(first)
    resume_compute()
    assert claim() == run.id
    next_key = "red" if next_algorithm == "ndvi" else "green"
    question = band_question()
    question["arguments"]["title"] = "继续分析前确认新波段"
    question["arguments"]["questions"][0].update(key=next_key, label=next_key)
    mock_model(
        monkeypatch,
        [
            {
                "action": "read_compute_output",
                "arguments": {"outputId": initial_output.id},
            },
            question,
        ],
    )
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "waiting_input"
    chosen = {next_key: "5" if next_key == "red" else "2", "nir": "7"}
    assert submit_answer(env, run, answers=chosen).status_code == 202
    assert claim() == run.id
    parameters = {key: int(value) for key, value in chosen.items()}
    command = {
        "action": "execute_operator",
        "arguments": {
            "versionId": env[next_algorithm].id,
            "inputs": {"image": env["raster"].id},
            "parameters": parameters,
        },
    }
    mock_model(monkeypatch, [command])
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "waiting_compute"
    assert ComputeTask.objects.count() == 2
    second = ComputeTask.objects.exclude(pk=first.id).get()
    assert (
        second.parameters == parameters and second.version_id == env[next_algorithm].id
    )
    assert run.execution_state["computePlans"][0]["taskId"] == str(first.id)
    assert run.compute_intent["taskId"] == str(second.id)
    # A repeated model tool call cannot launch the new calculation twice.
    repeated, _ = execute(run, "execute_operator", command["arguments"])
    assert repeated["taskId"] == str(second.id) and ComputeTask.objects.count() == 2
    final_output = raster_output(second)
    resume_compute()
    assert claim() == run.id
    mock_model(
        monkeypatch,
        [
            {
                "action": "read_compute_output",
                "arguments": {"outputId": final_output.id},
            },
            {
                "action": "final",
                "answer": "根据补充条件调整了波段，两个实际计算结果已读取。",
            },
        ],
    )
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "succeeded" and run.compute_followups.count() == 2
    assert run.execution_state["computePlans"][0]["taskId"] == str(first.id)


def test_model_cannot_silently_change_user_parameters_after_first_calculation(
    raster_env, monkeypatch
):
    from django.core.exceptions import ValidationError

    env = raster_env
    run = make_run(env, "计算NDVI，red=3 nir=8")
    mock_model(monkeypatch, [run_command(env)])
    run_task(run.id)
    run.refresh_from_db()
    with pytest.raises(ValidationError, match="明确选择的参数"):
        execute(run, "execute_operator", run_command(env, red=5)["arguments"])
    assert ComputeTask.objects.count() == 1


def test_supplement_conflicts_with_structured_choice_then_confirms_latest_plan(
    raster_env, monkeypatch
):
    env = raster_env
    run = make_run(env)
    mock_model(monkeypatch, [band_question()])
    run_task(run.id)
    assert (
        submit_answer(
            env, run, text="更正，红光改为第5波段，近红外仍第8波段，先不入库"
        ).status_code
        == 202
    )
    assert claim() == run.id
    captured = []
    mock_model(
        monkeypatch,
        [
            run_command(env, red=5),
            band_question("您选了红光3，同时补充改为5，请确认最终波段"),
        ],
        captured,
    )
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "waiting_input" and not ComputeTask.objects.exists()
    assert (
        submit_answer(
            env,
            run,
            submissionKey="bands-final-confirmation",
            answers={"red": "5", "nir": "8"},
            text="确认红光第5波段，近红外第8波段，以这次确认为准",
        ).status_code
        == 202
    )
    assert claim() == run.id
    mock_model(monkeypatch, [run_command(env, red=5)])
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "waiting_compute"
    assert ComputeTask.objects.get().parameters == {"red": 5, "nir": 8}


@pytest.mark.parametrize("cancel_import", [False, True])
def test_latest_answer_changes_auto_import_authority(
    raster_env, monkeypatch, cancel_import
):
    env = raster_env
    run = make_run(env, "计算NDVI，先不入库")
    card = band_question()
    card["arguments"]["questions"].append(
        {
            "key": "autoImport",
            "label": "是否自动入库",
            "type": "single",
            "required": True,
            "options": [
                {"value": "true", "label": "是"},
                {"value": "false", "label": "否"},
            ],
        }
    )
    mock_model(monkeypatch, [card])
    run_task(run.id)
    text = "这次先不入库" if cancel_import else "更改为自动入库"
    assert (
        submit_answer(
            env, run, answers={"red": "3", "nir": "8", "autoImport": "true"}, text=text
        ).status_code
        == 202
    )
    assert claim() == run.id
    command = run_command(env)
    command["arguments"]["autoImport"] = not cancel_import
    mock_model(monkeypatch, [command])
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "waiting_compute"
    assert ComputeTask.objects.count() == 1
    assert run.compute_intent["autoImport"] is not cancel_import
    assert run.compute_followups.get().auto_import is not cancel_import


@pytest.mark.parametrize("red", [None, 3])
def test_unsubmitted_compute_plan_cannot_be_marked_completed(
    raster_env, monkeypatch, red
):
    env = raster_env
    run = make_run(env, "计算NDVI，red=3 nir=8" if red else "计算NDVI")
    from apps.agent.compute_intents import _prepare

    _prepare(run, env["owner"], env["policy"], env["ndvi"])
    captured = []
    commands = [{"action": "final", "answer": "请使用参数卡片运行。"}]
    commands.append(run_command(env) if red else band_question())
    mock_model(monkeypatch, commands, captured)
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == ("waiting_compute" if red else "waiting_input")
    assert "不能用final结束" in json.dumps(captured[-1], ensure_ascii=False)
    assert ComputeTask.objects.count() == bool(red)


def test_conflicting_supplement_final_is_corrected_to_second_question(
    raster_env, monkeypatch
):
    env = raster_env
    run = make_run(env)
    mock_model(monkeypatch, [band_question()])
    run_task(run.id)
    assert (
        submit_answer(
            env, run, text="更正，红光改为第5波段，近红外仍第8波段"
        ).status_code
        == 202
    )
    assert claim() == run.id
    captured = []
    mock_model(
        monkeypatch,
        [
            run_command(env, red=5),
            {"action": "final", "answer": "请使用下方计算卡片运行。"},
            band_question("选项为红光3，补充文字为5，请确认最终选择"),
        ],
        captured,
    )
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "waiting_input" and not ComputeTask.objects.exists()
    assert run.interaction["revision"] == 2
    assert "不能用final结束" in json.dumps(captured[-1], ensure_ascii=False)
    assert (
        submit_answer(
            env,
            run,
            submissionKey="confirmed-second-card",
            answers={"red": "5", "nir": "8"},
        ).status_code
        == 202
    )
    assert claim() == run.id
    mock_model(monkeypatch, [run_command(env, red=5)])
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "waiting_compute"
    assert ComputeTask.objects.get().parameters == {"red": 5, "nir": 8}


def test_user_changes_goal_to_explanation_and_cancels_only_pending_plan(
    raster_env, monkeypatch
):
    env = raster_env
    run = make_run(env)
    mock_model(monkeypatch, [run_command(env), band_question()])
    run_task(run.id)
    run.refresh_from_db()
    assert run.compute_intent["status"] == "collecting"
    assert (
        submit_answer(
            env, run, answers={}, text="取消计算，改为只解释NDVI原理"
        ).status_code
        == 202
    )
    assert claim() == run.id
    mock_model(
        monkeypatch,
        [
            run_command(env),
            {
                "action": "final",
                "answer": "NDVI比较近红外与红光；已按您的要求改为原理说明。",
            },
        ],
    )
    run_task(run.id)
    run.refresh_from_db()
    assert run.status == "succeeded" and run.compute_intent["status"] == "cancelled"
    assert "NDVI比较近红外" in run.answer
    assert not ComputeTask.objects.exists()


@pytest.mark.parametrize("selected, expected", [("explain", True), ("compute", False)])
def test_only_actual_selected_choice_can_cancel_pending_compute(selected, expected):
    from types import SimpleNamespace
    from apps.agent.compute_intent_text import user_cancelled_pending_compute

    run = SimpleNamespace(
        prompt="计算NDVI",
        interaction_history=[
            {
                "status": "answered",
                "title": "是否取消计算，只解释原理",
                "questions": [
                    {
                        "key": "goal",
                        "label": "是否取消计算，只解释原理",
                        "options": [
                            {"value": "explain", "label": "取消计算，只解释原理"},
                            {"value": "compute", "label": "继续实际计算"},
                        ],
                    }
                ],
                "answer": {"answers": {"goal": selected}, "text": ""},
            }
        ],
    )
    assert user_cancelled_pending_compute(run) is expected
    run.interaction_history[0]["answer"]["text"] = "不要取消计算，只解释当前选择的参数"
    assert not user_cancelled_pending_compute(run)


def test_stale_parameter_submit_cannot_restart_a_cancelled_plan(raster_env):
    from apps.agent.compute_intents import _prepare, update
    from apps.compute.packages import ComputeError
    from apps.agent.models import AgentRun

    env = raster_env
    run = make_run(env, "计算NDVI，red=3 nir=8")
    run.status = "succeeded"
    run.save(update_fields=["status"])
    _prepare(run, env["owner"], env["policy"], env["ndvi"])
    revision = run.compute_intent["planRevision"]
    AgentRun.objects.filter(pk=run.pk).update(
        compute_intent={**run.compute_intent, "status": "cancelled"}
    )
    with pytest.raises(ComputeError, match="替代或取消"):
        update(
            run,
            env["owner"],
            env["policy"],
            {"action": "submit", "planRevision": revision},
        )
    assert not ComputeTask.objects.exists()


def test_cancellation_during_discovery_blocks_actual_compute_submission(
    raster_env, monkeypatch
):
    from django.core.exceptions import PermissionDenied
    from apps.agent import compute_intents

    env = raster_env
    run = make_run(env, "计算NDVI，red=3 nir=8")
    prepare = compute_intents.prepare_from_tool

    def cancelled_after_discovery(*args):
        result = prepare(*args)
        AgentRun.objects.filter(pk=run.pk).update(
            cancel_requested=True, status="cancelled"
        )
        return result

    monkeypatch.setattr(compute_intents, "prepare_from_tool", cancelled_after_discovery)
    with pytest.raises(PermissionDenied, match="已停止"):
        execute(run, "execute_operator", run_command(env)["arguments"])
    assert not ComputeTask.objects.exists()


@pytest.mark.parametrize("choice, expected", [("no", False), ("yes", True)])
def test_import_question_label_does_not_authorize_rejected_choice(choice, expected):
    from types import SimpleNamespace
    from apps.agent.compute_intents import user_import_choice

    run = SimpleNamespace(
        prompt="是否自动入库？",
        interaction_history=[
            {
                "status": "answered",
                "questions": [
                    {
                        "key": "store",
                        "label": "是否自动入库",
                        "options": [
                            {"value": "yes", "label": "是"},
                            {"value": "no", "label": "否"},
                        ],
                    }
                ],
                "answer": {"answers": {"store": choice}, "text": ""},
            }
        ],
    )
    assert user_import_choice(run) is expected
    run.interaction_history = []
    assert user_import_choice(run) is False


@pytest.mark.parametrize("key", ["store", "autoImport"])
def test_import_text_question_can_cancel_previous_permission(key):
    from types import SimpleNamespace
    from apps.agent.compute_intents import user_import_choice

    run = SimpleNamespace(
        prompt="请自动入库",
        interaction_history=[
            {
                "status": "answered",
                "questions": [
                    {"key": key, "label": "是否自动入库", "type": "text", "options": []}
                ],
                "answer": {"answers": {key: "不要自动入库"}, "text": ""},
            }
        ],
    )
    assert user_import_choice(run) is False
