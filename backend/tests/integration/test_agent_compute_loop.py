"""Regression for queued snapshots, UUID/output confusion and durable import."""

import json
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError

from apps.agent.models import (
    AgentPolicy,
    AgentRun,
    Conversation,
    AgentComputeFollowup,
    AgentWorkflow,
)
from apps.agent.policy import default_policy
from apps.agent.tools import execute, evidence_items
from apps.agent.compute_tools import resume_followups
from apps.agent.workflow import run_workflow, resume_waiting
from apps.compute.models import ComputeTask, ComputeOutput, ComputeImport
from apps.compute.services import submit, ComputeError
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import ProjectMembership
from tests.integration.test_compute import setup_compute  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def env(setup_compute, settings):  # noqa: F811 - pytest fixture dependency
    e = setup_compute
    settings.AGENT_MODELS = [
        {
            "alias": "mock",
            "name": "Mock",
            "base_url": "http://127.0.0.1:19100/v1",
            "model_id": "mock",
            "agent": True,
        }
    ]
    e["owner"].user_permissions.add(
        *Permission.objects.filter(
            codename__in=["use_local_model", "use_data_agent", "query_data"]
        )
    )
    policy = default_policy()
    policy["operatorEnabled"] = True
    AgentPolicy.objects.create(value=policy)
    e["scope"] = ProjectScope((e["project"].id,), e["project"].id, e["owner"].id)
    with project_scope(e["scope"]):
        conversation = Conversation.objects.create(owner=e["owner"], mode="agent")
        e["run"] = AgentRun.objects.create(
            conversation=conversation,
            owner=e["owner"],
            model="mock",
            prompt="计算并入库",
            idempotency_key="compute-loop",
            status="succeeded",
        )
        yield e


def task(e):
    result = submit(e["owner"], e["body"])
    AgentComputeFollowup.objects.create(task=result, run=e["run"])
    return result


def output(t, key="summary"):
    t.status = "succeeded"
    t.save(update_fields=["status"])
    return ComputeOutput.objects.create(
        task=t,
        key=key,
        label=key,
        kind="table",
        file_name=key + ".csv",
        path="unused.csv",
        size_bytes=3,
        checksum="a" * 64,
        metadata={},
    )


def test_realtime_task_returns_real_integer_outputs(env):
    t = task(env)
    before, _ = execute(env["run"], "get_compute_task", {"taskId": str(t.id)})
    assert before["status"] == "queued"
    o = output(t)
    after, _ = execute(env["run"], "get_compute_task", {"taskId": str(t.id)})
    assert after["status"] == "succeeded"
    assert after["outputs"][0]["id"] == o.id
    assert type(after["outputs"][0]["id"]) is int


def test_task_id_import_waits_and_resumes_once(env):
    t = task(env)
    result, _ = execute(env["run"], "import_compute_result", {"taskId": str(t.id)})
    assert result["trackingStatus"] == "waiting_compute"
    assert not ComputeImport.objects.exists()
    o = output(t)
    resume_followups()
    resume_followups()
    record = ComputeImport.objects.get(output=o)
    assert record.status == "queued"
    assert AgentComputeFollowup.objects.get(task=t).status == "waiting_import"
    record.status, record.resource = "ready", env["resource"]
    record.save()
    resume_followups()
    assert AgentComputeFollowup.objects.get(task=t).status == "completed"
    assert ComputeImport.objects.count() == 1


def test_real_agent_result_import_uses_compute_category(env):
    from apps.compute.data import inspect_output
    from apps.compute.packages import checksum
    from apps.compute.worker import process_import
    from apps.core.storage import app_path

    t = task(env)
    o = output(t)
    path = app_path(
        "projects",
        str(t.project_tag_id),
        "compute",
        "outputs",
        str(t.id),
        "summary.csv",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("region,value\nA,3\n", encoding="utf-8")
    o.path = path.relative_to(app_path()).as_posix()
    o.size_bytes = path.stat().st_size
    o.checksum = checksum(path)
    o.metadata = inspect_output(path, "table")
    o.save()
    execute(env["run"], "import_compute_result", {"taskId": str(t.id)})
    record = ComputeImport.objects.get(output=o)
    assert record.request_source == f"agent_run:{env['run'].id}"
    process_import(record)
    record.refresh_from_db()
    assert record.status == "ready", record.error
    assert record.resource.is_compute_result
    assert record.resource.category.code == "compute_results"
    assert record.resource.project_tag_id == env["project"].id
    assert not env["resource"].is_compute_result
    value, _ = execute(env["run"], "get_compute_task", {"taskId": str(t.id)})
    assert " / 数据资源 / 计算结果 / " in value["outputs"][0]["resourceLocation"]


def test_multiple_outputs_and_repeated_import_do_not_duplicate(env):
    t = task(env)
    output(t, "first")
    output(t, "second")
    args = {"taskId": str(t.id)}
    execute(env["run"], "import_compute_result", args)
    execute(env["run"], "import_compute_result", args)
    assert ComputeImport.objects.count() == 2


def test_uuid_is_never_accepted_as_output_id(env):
    with pytest.raises(ValidationError, match="正整数"):
        execute(env["run"], "import_compute_result", {"outputId": str(task(env).id)})


def test_revocation_stops_automatic_import(env):
    t = task(env)
    execute(env["run"], "import_compute_result", {"taskId": str(t.id)})
    output(t)
    ProjectMembership.objects.filter(user=env["owner"], project=env["project"]).delete()
    resume_followups()
    assert not ComputeImport.objects.exists()
    assert AgentComputeFollowup.objects.get(task=t).status == "blocked"


def test_cross_project_and_other_owner_queries_are_rejected(env):
    t = task(env)
    t.owner = env["outsider"]
    t.save(update_fields=["owner"])
    with pytest.raises(ComputeError, match="无权"):
        execute(env["run"], "get_compute_task", {"taskId": str(t.id)})
    with project_scope(ProjectScope((1,), 1, env["owner"].id)):
        with pytest.raises(PermissionDenied):
            execute(env["run"], "get_compute_task", {"taskId": str(t.id)})


def test_explicit_algorithm_deny_and_public_discovery(env):
    result, _ = execute(env["run"], "list_compute_algorithms", {})
    assert result["items"][0]["id"] == env["version"].algorithm_id
    v = env["version"]
    v.manifest = {**v.manifest, "agent": {"enabled": False}}
    v.save(update_fields=["manifest"])
    with pytest.raises(PermissionDenied, match="未允许"):
        execute(
            env["run"],
            "execute_operator",
            {
                "versionId": v.id,
                "inputs": env["body"]["inputs"],
                "parameters": env["body"]["parameters"],
            },
        )


def test_algorithm_goal_search_keeps_complete_manifest_and_empty_fallback(env):
    from apps.compute.models import AlgorithmResource, AlgorithmVersion

    version = env["version"]
    algorithm = version.algorithm
    algorithm.name = "矢量面积与周长"
    algorithm.description = "WGS84 椭球量测，保留孔洞"
    algorithm.identifier = "vector-metrics"
    with project_scope(
        ProjectScope(
            (algorithm.project_tag_id,), algorithm.project_tag_id, env["admin"].id
        )
    ):
        algorithm.save(update_fields=["name", "description", "identifier"])
    other = AlgorithmResource.objects.create(
        identifier="raster-classifier", name="影像分类", created_by=env["owner"]
    )
    AlgorithmVersion.objects.create(
        algorithm=other,
        version="1",
        status="published",
        manifest=version.manifest,
        checksum="b" * 64,
        package_path="unused.zip",
    )
    for query in ["面积 周长", "量测", "vector-metrics", "未命中词 面积"]:
        result, _ = execute(env["run"], "list_compute_algorithms", {"query": query})
        assert [item["id"] for item in result["items"]] == [algorithm.id]
        selected = result["items"][0]["versions"][0]
        assert selected["manifest"] == version.manifest
        assert selected["manifest"]["inputs"] == version.manifest["inputs"]
        assert selected["manifest"]["parameters"] == version.manifest["parameters"]
        assert selected["manifest"]["outputs"] == version.manifest["outputs"]
    all_items, _ = execute(env["run"], "list_compute_algorithms", {})
    assert {item["id"] for item in all_items["items"]} == {algorithm.id, other.id}
    missing, _ = execute(
        env["run"], "list_compute_algorithms", {"query": "完全不存在的算法"}
    )
    assert missing["items"] == [] and not missing["truncated"]
    with pytest.raises(ValidationError, match="算法关键词"):
        execute(env["run"], "list_compute_algorithms", {"query": ["面积"]})


def test_model_changed_keys_cannot_repeat_calculation(env):
    env["run"].prompt = "计算表格统计，group=region value=value method=mean，自动入库"
    env["run"].save(update_fields=["prompt"])
    args = {
        "versionId": env["version"].id,
        "inputs": env["body"]["inputs"],
        "parameters": env["body"]["parameters"],
        "autoImport": True,
    }
    first, _ = execute(
        env["run"], "execute_operator", {**args, "idempotencyKey": "first-key"}
    )
    second, _ = execute(
        env["run"], "execute_operator", {**args, "idempotencyKey": "new-key"}
    )
    assert first["taskId"] == second["taskId"]
    assert ComputeTask.objects.count() == 1


def test_live_http_cards_support_historical_evidence(env):
    t = task(env)
    result, pairs = execute(env["run"], "get_compute_task", {"taskId": str(t.id)})
    env["run"].evidence = evidence_items(env["run"], "get_compute_task", pairs)
    env["run"].save()
    output(t)
    response = env["client"].get(
        f"/api/agent/runs/{env['run'].id}/compute-tasks/",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["task"]["status"] == "succeeded"


def workflow(e, **overrides):
    return AgentWorkflow.objects.create(
        owner=e["owner"],
        model="mock",
        goal="使用表格统计并入库",
        resource_ids=[e["resource"].id],
        algorithm_version_id=e["version"].id,
        parameters=e["body"]["parameters"],
        idempotency_key="loop-workflow",
        **overrides,
    )


def test_workflow_preview_confirm_compute_then_import(env):
    w = workflow(env)
    run_workflow(w.id)
    w.refresh_from_db()
    assert w.status == "waiting_approval"
    assert not ComputeTask.objects.exists()
    response = env["client"].post(
        f"/api/agent/workflows/{w.id}/confirm/",
        json.dumps({"planHash": w.plan_hash}),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )
    assert response.status_code == 200, response.content
    run_workflow(w.id)
    t = ComputeTask.objects.get()
    o = output(t)
    resume_waiting()
    record = ComputeImport.objects.get(output=o)
    record.status, record.resource = "ready", env["resource"]
    record.save()
    resume_waiting()
    w.refresh_from_db()
    assert w.status == "succeeded"
    assert w.result_resource_ids == [env["resource"].id]


def test_goal_without_match_never_picks_arbitrary_algorithm(env):
    w = workflow(env)
    w.algorithm_version_id = None
    w.goal = "分析任意未知目标"
    w.save()
    run_workflow(w.id)
    w.refresh_from_db()
    assert w.status == "failed"
    assert "未唯一匹配" in w.detail
    assert not ComputeTask.objects.exists()


def test_conflict_keeps_original_result_without_import(env):
    from apps.knowledge.models import KnowledgeEntry

    entry = KnowledgeEntry.objects.create(
        title="冲突条件", status="published", revision=1
    )
    w = workflow(env)
    run_workflow(w.id)
    w.refresh_from_db()
    w.execute_operators, w.status = True, "queued"
    w.save()
    run_workflow(w.id)
    output(ComputeTask.objects.get())
    w.evidence = [{"id": entry.id, "revision": 1}]
    w.save(update_fields=["evidence"])
    with patch(
        "apps.knowledge.services.check_constraints",
        return_value={"checked": 1, "findings": [{"status": "conflict"}]},
    ):
        resume_waiting()
    w.refresh_from_db()
    assert w.status == "failed"
    assert ComputeOutput.objects.count() == 1
    assert not ComputeImport.objects.exists()


def test_cancel_waiting_workflow_cancels_compute_without_import(env):
    w = workflow(env)
    run_workflow(w.id)
    w.refresh_from_db()
    w.execute_operators, w.status = True, "queued"
    w.save()
    run_workflow(w.id)
    w.cancel_requested = True
    w.save(update_fields=["cancel_requested"])
    resume_waiting()
    w.refresh_from_db()
    assert w.status == "cancelled"
    assert ComputeTask.objects.get().status == "cancelled"
    assert not ComputeImport.objects.exists()


def test_changed_input_refuses_confirmation(env):
    w = workflow(env)
    run_workflow(w.id)
    w.refresh_from_db()
    resource = env["resource"]
    resource.description = "更新后的数据"
    resource.save()
    response = env["client"].post(
        f"/api/agent/workflows/{w.id}/confirm/",
        json.dumps({"planHash": w.plan_hash}),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )
    assert response.status_code == 400
    assert "已变化" in response.json()["detail"]
    assert not ComputeTask.objects.exists()


def test_cancel_after_import_queued_is_checked_at_import_start(env):
    from apps.compute.worker import process_import

    t = task(env)
    o = output(t)
    execute(env["run"], "import_compute_result", {"taskId": str(t.id)})
    record = ComputeImport.objects.get(output=o)
    env["run"].cancel_requested = True
    env["run"].save(update_fields=["cancel_requested"])
    with patch("apps.compute.worker.import_output") as importer:
        process_import(record)
    importer.assert_not_called()
    record.refresh_from_db()
    assert record.status == "failed"
    assert "已取消" in record.error


def test_revoked_policy_stops_queued_import_before_copying(env):
    from apps.compute.worker import process_import

    t = task(env)
    o = output(t)
    execute(env["run"], "import_compute_result", {"taskId": str(t.id)})
    saved = AgentPolicy.objects.get()
    saved.value["operatorEnabled"] = False
    saved.save()
    record = ComputeImport.objects.get(output=o)
    with patch("apps.compute.worker.import_output") as importer:
        process_import(record)
    importer.assert_not_called()
    record.refresh_from_db()
    assert record.status == "failed"
    assert "权限已关闭" in record.error


def test_explicit_manual_retry_clears_cancelled_automatic_intent(env):
    from apps.compute.worker import process_import
    from apps.compute.services import request_output_import

    t = task(env)
    o = output(t)
    execute(env["run"], "import_compute_result", {"taskId": str(t.id)})
    record = ComputeImport.objects.get(output=o)
    env["run"].cancel_requested = True
    env["run"].save(update_fields=["cancel_requested"])
    process_import(record)
    request_output_import(env["owner"], o)
    record.refresh_from_db()
    assert record.request_source == ""
    with patch(
        "apps.compute.worker.import_output", return_value=env["resource"]
    ) as importer:
        process_import(record)
    importer.assert_called_once()
    record.refresh_from_db()
    assert record.status == "ready"
    assert ComputeImport.objects.count() == 1


def test_database_defaults_allow_old_workflow_insert(env):
    import uuid
    from django.db import connection

    original = workflow(env)
    original.status = "succeeded"
    original.save()
    new_id = uuid.uuid4()
    excluded = {"plan", "plan_hash", "import_results", "result_resource_ids"}
    columns = [
        field.column
        for field in AgentWorkflow._meta.local_fields
        if field.name not in excluded
    ]
    expressions, params = [], []
    for column in columns:
        if column in {"id", "idempotency_key"}:
            expressions.append("%s")
            params.append(new_id.hex if column == "id" else "legacy-insert")
        else:
            expressions.append(connection.ops.quote_name(column))
    params.append(original.id.hex)
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO agent_agentworkflow ({', '.join(connection.ops.quote_name(c) for c in columns)}) SELECT {', '.join(expressions)} FROM agent_agentworkflow WHERE id=%s",
            params,
        )
    restored = AgentWorkflow.objects.get(pk=new_id)
    assert restored.plan == {}
    assert restored.plan_hash == ""
    assert restored.import_results is True
    assert restored.result_resource_ids == []
