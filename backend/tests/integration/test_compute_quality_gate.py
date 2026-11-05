# ruff: noqa: F811

import json
from unittest.mock import patch

import pytest

from apps.agent.compute_tools import resume_followups
from apps.agent.models import AgentComputeFollowup
from apps.agent.tools import execute
from apps.agent.workflow import resume_waiting, run_workflow
from apps.compute.models import ComputeImport, ComputeTask
from apps.compute.quality import quality_metadata
from apps.compute.services import ComputeError, request_output_import
from tests.integration.test_agent_compute_loop import env, output, task, workflow  # noqa: F401
from tests.integration.test_compute import setup_compute  # noqa: F401


def checked_output(t, status="needs_review"):
    t.version.manifest = {
        **t.version.manifest,
        "qualityReport": {"file": "quality.json"},
    }
    t.version.save(update_fields=["manifest"])
    result = output(t)
    result.metadata = quality_metadata(
        {
            "version": 1,
            "status": status,
            "summary": "发现面自相交，面积变化需审核",
            "metrics": {"needsReview": 1},
            "knowledgeFacts": {"geometryRepair": {"needsReview": 1}},
        }
    )
    result.save(update_fields=["metadata"])
    return result


def test_direct_agent_import_stops_on_quality_review(env):  # noqa: F811
    t = task(env)
    result = checked_output(t)
    with pytest.raises(ComputeError, match="需要审核"):
        execute(env["run"], "import_compute_result", {"outputId": result.id})
    assert not ComputeImport.objects.exists()


def test_chat_import_feedback_omits_quality_summary_but_result_card_retains_it(
    env, monkeypatch
):  # noqa: F811
    from apps.agent.worker import run_task
    from apps.compute.serializers import output_data
    from tests.integration.test_agent_interactions import mock_model

    t = task(env)
    result = checked_output(t)
    summary = "C:/private/input.gpkg upstream-token=diagnostic-secret"
    result.metadata["qualityCheck"]["summary"] = summary
    result.save(update_fields=["metadata"])
    item = env["run"]
    assert AgentComputeFollowup.objects.get(task=t).run_id == item.id
    item.prompt, item.status = "入库", "running"
    item.save(update_fields=["prompt", "status"])
    feedback = (
        "结果需要审核，已保留原始输出并暂停自动入库；请查看结果卡中的质量核查说明"
    )
    captured = []
    mock_model(
        monkeypatch,
        [
            {"action": "import_compute_result", "arguments": {"taskId": str(t.id)}},
            {"action": "final", "answer": feedback},
        ],
        captured,
    )
    with patch("apps.agent.worker.guard"):
        run_task(item.id)
    item.refresh_from_db()
    assert item.status == "succeeded", item.detail
    assert feedback in item.answer
    assert len(captured) == 2
    assert feedback in json.dumps(captured[1], ensure_ascii=False)
    assert summary not in json.dumps(captured, ensure_ascii=False)
    assert summary not in item.detail + item.answer
    assert not item.events.filter(text__contains=summary).exists()
    result.refresh_from_db()
    assert output_data(result)["metadata"]["qualityCheck"]["summary"] == summary
    assert not ComputeImport.objects.exists()


def test_automatic_followup_stops_on_quality_review_and_preserves_output(env):  # noqa: F811
    t = task(env)
    execute(env["run"], "import_compute_result", {"taskId": str(t.id)})
    result = checked_output(t)
    resume_followups()
    followup = AgentComputeFollowup.objects.get(task=t)
    assert followup.status == "blocked"
    assert "需要审核" in followup.detail
    assert not ComputeImport.objects.exists()
    assert t.outputs.filter(pk=result.pk).exists()


def test_workflow_stops_automatic_import_on_quality_review(env):  # noqa: F811
    w = workflow(env)
    run_workflow(w.id)
    w.refresh_from_db()
    w.execute_operators, w.status = True, "queued"
    w.save()
    run_workflow(w.id)
    result = checked_output(ComputeTask.objects.get())
    resume_waiting()
    w.refresh_from_db()
    assert w.status == "failed"
    assert "需要审核" in w.detail
    assert result.id in w.result_ids
    assert not ComputeImport.objects.exists()


def test_queued_automatic_import_rechecks_quality_before_processing(env):  # noqa: F811
    from apps.compute.worker import process_import

    t = task(env)
    result = checked_output(t, status="passed")
    execute(env["run"], "import_compute_result", {"outputId": result.id})
    record = ComputeImport.objects.get(output=result)
    result.metadata["qualityCheck"]["status"] = "needs_review"
    result.save(update_fields=["metadata"])
    with patch("apps.compute.worker.import_output") as import_output:
        process_import(record)
    record.refresh_from_db()
    assert record.status == "failed"
    assert "需要审核" in record.error
    import_output.assert_not_called()


def test_manual_import_is_explicit_and_does_not_override_agent_gate(env):  # noqa: F811
    result = checked_output(task(env))
    record = request_output_import(env["owner"], result, "审核后入库")
    assert record.request_source == ""
    with pytest.raises(ComputeError, match="需要审核"):
        request_output_import(
            env["owner"], result, request_source=f"agent_run:{env['run'].id}"
        )


def test_worker_attaches_declared_quality_facts_to_all_outputs(env):  # noqa: F811
    from apps.compute.worker import run_task, task_scope

    t = task(env)
    # The existing fixture package has no quality declaration; add it to the
    # validated manifest as if it had been registered with this optional field.
    original_manifest = t.version.manifest
    t.version.manifest = {
        **original_manifest,
        "qualityReport": {"file": "quality.json"},
    }
    t.version.save(update_fields=["manifest"])

    def inspect_package(path, extract_to=None):
        return {**original_manifest, "qualityReport": {"file": "quality.json"}}

    def execute_fixture(attempt, package, inputs, destination, manifest, heartbeat):
        (destination / "summary.csv").write_text("group,value\nA,3\n", encoding="utf-8")
        (destination / "quality.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "status": "needs_review",
                    "summary": "复核数值",
                    "metrics": {"needsReview": 1},
                    "knowledgeFacts": {"x": 1},
                }
            ),
            encoding="utf-8",
        )

    with (
        task_scope(t),
        patch("apps.compute.worker.inspect_package", side_effect=inspect_package),
        patch("apps.compute.worker.execute", side_effect=execute_fixture),
    ):
        run_task(t)
    t.refresh_from_db()
    assert t.status == "succeeded", t.error
    result = t.outputs.get()
    assert result.metadata["qualityCheck"]["status"] == "needs_review"
    assert result.metadata["knowledgeFacts"] == {"x": 1}
