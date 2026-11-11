"""Batch output reads retain file checks and fresh authorization at both ends."""
# ruff: noqa: F811 - pytest fixtures are injected by name.

from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied

from apps.agent import demo_results
from apps.agent.demo_workflow import prepare_demo, confirm_demo, advance_demo
from apps.compute.models import ComputeOutput
from apps.core.storage import app_path
from apps.projects.models import ProjectMembership
from tests.integration.test_demo_workflow import demo, scenario, finish_task  # noqa: F401
from tests.integration.test_compute import setup_compute  # noqa: F401

pytestmark = pytest.mark.django_db


def results(env):
    workflow = scenario(env)
    prepare_demo(workflow, env["owner"], env["policy"])
    confirm_demo(workflow, env["owner"], env["policy"], workflow.plan_hash)
    advance_demo(workflow.id)
    output = finish_task(workflow)
    workflow.refresh_from_db()
    for index in range(1, 25):
        ComputeOutput.objects.create(
            task=output.task,
            key=f"sample_{index}",
            label="统计",
            kind=output.kind,
            file_name=output.file_name,
            path=output.path,
            size_bytes=output.size_bytes,
            checksum=output.checksum,
            metadata=output.metadata,
        )
    return workflow, output


def test_many_outputs_share_task_authorization_but_keep_each_file_check(demo):
    workflow, output = results(demo)
    with patch.object(
        demo_results, "authorized_task", wraps=demo_results.authorized_task
    ) as authorized:
        actual = demo_results.read_results(
            workflow, demo["owner"], demo["policy"], output.task
        )
    assert len(actual) == 25 and authorized.call_count == 2
    app_path(output.path).write_text("文件已变化", encoding="utf-8")
    with pytest.raises(demo_results.ComputeError, match="文件内容已变化"):
        demo_results.read_results(workflow, demo["owner"], demo["policy"], output.task)


def test_revocation_during_batch_read_blocks_returning_collected_rows(
    demo, monkeypatch
):
    workflow, output = results(demo)
    # read_results reads every output through _read_task_output after one
    # task check; revoking during that loop must still fail the final check.
    original = demo_results._read_task_output
    checked = []

    def revoke(*args):
        value = original(*args)
        if not checked:
            checked.append(True)
            ProjectMembership.objects.filter(
                project=demo["project"], user=demo["owner"]
            ).delete()
        return value

    monkeypatch.setattr(demo_results, "_read_task_output", revoke)
    with pytest.raises((PermissionDenied, demo_results.ComputeError)):
        demo_results.read_results(workflow, demo["owner"], demo["policy"], output.task)


def test_import_poll_does_not_repeat_full_authorization_or_rewrite_plan_per_output(
    demo,
):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from apps.agent import demo_workflow
    from apps.compute.models import ComputeImport

    workflow, output = results(demo)
    stage = workflow.plan["stages"][workflow.plan["stageIndex"]]
    with patch.object(
        demo_workflow, "_authorize", wraps=demo_workflow._authorize
    ) as authorize:
        assert not demo_workflow._collect_stage(
            workflow, demo["owner"], demo["policy"], stage, output.task
        )
        assert authorize.call_count == 2
    assert ComputeImport.objects.count() == 25
    workflow.refresh_from_db()
    stage = workflow.plan["stages"][workflow.plan["stageIndex"]]
    with (
        patch.object(
            demo_workflow, "_authorize", wraps=demo_workflow._authorize
        ) as authorize,
        CaptureQueriesContext(connection) as queries,
    ):
        assert not demo_workflow._collect_stage(
            workflow, demo["owner"], demo["policy"], stage, output.task
        )
        assert authorize.call_count == 1
    assert workflow.detail == "正在入库：已完成 0/25 项成果"
    assert not any('SET "plan"' in query["sql"] for query in queries)


@pytest.mark.parametrize("slow,expected", [(False, 8), (True, 2)])
def test_import_queue_processes_a_bounded_batch_without_sleeping_between_items(
    demo, monkeypatch, slow, expected
):
    from apps.compute import worker
    from apps.compute.models import ComputeImport
    from apps.compute.services import request_output_import
    from apps.projects.context import current_scope

    _, output = results(demo)
    for item in output.task.outputs.all():
        request_output_import(demo["owner"], item)
    clock, processed = [0.0], []

    def process(item):
        assert current_scope.get().selected == item.output.task.project_tag_id
        processed.append(item.pk)
        ComputeImport.objects.filter(pk=item.pk).update(status="ready")
        clock[0] += 3 if slow else 0

    monkeypatch.setattr(worker.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(worker, "inspect_runtime", lambda: {"ready": True})
    monkeypatch.setattr(worker, "clean_expired", lambda: None)
    monkeypatch.setattr(worker, "process_import", process)
    assert worker.worker_tick(recovered=True)
    assert len(processed) == expected
    assert ComputeImport.objects.filter(status="queued").count() == 25 - expected
