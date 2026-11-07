"""Report files are real, durable and guarded by original evidence permissions."""

import json

import pytest
from django.contrib.auth.models import Permission

from apps.agent.models import AgentWorkflow
from apps.agent.workflow import step
from apps.agent.workflow_reports import _paths
from apps.agent.workflow_reports import generate_report, import_report, load_report
from apps.catalog.models import DataResource
from apps.compute.models import ComputeInput, ComputeOutput, ComputeTask
from apps.compute.packages import checksum
from apps.core.storage import app_path
from apps.knowledge.models import KnowledgeEntry
from apps.knowledge.services import serialize
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo, scenario  # noqa: F401


@pytest.fixture
def completed(demo):  # noqa: F811
    env = demo
    workflow = scenario(env)
    workflow.status = "succeeded"
    workflow.detail = "实际统计表支持优先调查 A 区"
    knowledge = KnowledgeEntry.objects.create(
        title="植被下降调查规则",
        seed_key="report-rule",
        category="生态",
        subject="植被下降",
        predicate="需要",
        object="结合水分与质量资料",
        statement="植被下降需结合水分观测；低质量区域先补资料。",
        conditions=["同一季节", "输入质量通过"],
        exceptions=["云影响区域"],
        sources=[{"title": "演示调查说明", "locator": "第 2 页"}],
        status="published",
    )
    workflow.evidence = [serialize(knowledge)]
    decision = {
        "problem": "比较两期植被变化",
        "findings": ["A 区植被指数下降"],
        "judgement": "结合水分资料，优先调查 A 区",
        "uncertainties": ["B 区需补资料"],
        "algorithmReason": "使用分区统计读取真实变化",
        "resultSummary": "A 区下降 0.2",
        "nextAction": "finish",
        "evidenceRefs": [{"kind": "knowledge", "id": str(knowledge.id)}],
        "hiddenThinking": "SECRET_PRIVATE_THINKING",
    }
    task = ComputeTask.objects.create(
        owner=env["owner"],
        version=env["version"],
        name="生态真实统计",
        parameters={"group": "region", "value": "value", "method": "mean"},
        status="succeeded",
        progress=100,
        request_hash="a" * 64,
        idempotency_key="report-task",
    )
    ComputeInput.objects.create(task=task, key="table", resource=env["resource"])
    output_path = app_path(f"compute/test-report/{task.id}/statistics.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "region,ndvi_change,priority\nA,-0.2,调查\nB,,补资料\n", encoding="utf-8"
    )
    output = ComputeOutput.objects.create(
        task=task,
        key="statistics",
        label="调查优先区统计",
        kind="table",
        file_name="statistics.csv",
        path=output_path.relative_to(env["tmp"] / "app").as_posix(),
        size_bytes=output_path.stat().st_size,
        checksum=checksum(output_path),
    )
    workflow.plan.update(
        finalDecision=decision,
        stages=[
            {
                "name": "statistics",
                "taskId": str(task.id),
                "decision": decision,
                "rawResponse": "SECRET_RAW_RESPONSE",
            }
        ],
        privatePrompt="SECRET_INTERNAL_PROMPT",
        modelRequests=["SECRET_MODEL_REQUEST"],
    )
    workflow.result_ids = [output.id]
    workflow.save()
    step(
        workflow,
        "submit_operator",
        compute_task_id=task.id,
        action={"modelRequest": "SECRET_STEP_REQUEST"},
        message="实际统计已完成",
    )
    env.update(workflow=workflow, output=output, task=task, knowledge=knowledge)
    yield env


def request(env, suffix="", method="post", body=None):
    return getattr(env["client"], method)(
        f"/api/agent/workflows/{env['workflow'].id}/report/{suffix}",
        data=json.dumps(body or {}) if method == "post" else None,
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )


def test_multi_compact_report_preserves_previous_immutable_report(
    completed, monkeypatch
):
    env = completed
    workflow = env["workflow"]
    original = generate_report(workflow, env["owner"], env["policy"])
    old_path, old_metadata, _ = _paths(workflow)
    original_bytes, original_meta = old_path.read_bytes(), old_metadata.read_bytes()
    workflow.workflow_type = "geology_multi_element_reasoning"
    workflow.save(update_fields=["workflow_type"])
    monkeypatch.setattr(
        "apps.agent.workflow_reports.render_report",
        lambda *args: b"# Compact actual report\n",
    )
    compact = generate_report(workflow, env["owner"], env["policy"])
    new_path, _, _ = _paths(workflow)
    assert new_path != old_path and "compact-v2" in str(new_path)
    assert compact["checksum"] != original["checksum"]
    assert old_path.read_bytes() == original_bytes
    assert old_metadata.read_bytes() == original_meta
    imported = import_report(workflow, env["owner"], env["policy"])
    resource = DataResource.objects.get(pk=imported["resourceId"])
    assert resource.source.endswith(":compact-v2")
    assert "compact-v2" in resource.storage_path
    assert load_report(workflow, env["owner"])[0] == imported


def test_report_interpretation_revision_preserves_earlier_files(completed, monkeypatch):
    env = completed
    workflow = env["workflow"]
    workflow.workflow_type = "geology_generic"
    workflow.save(update_fields=["workflow_type"])
    monkeypatch.setattr(
        "apps.agent.workflow_reports.render_report",
        lambda *args: b"# Original analysis\n",
    )
    original = generate_report(workflow, env["owner"], env["policy"])
    original_path, metadata_path, _ = _paths(workflow)
    before = (original_path.read_bytes(), metadata_path.read_bytes())
    workflow.plan["reportInterpretationRevision"] = 1
    workflow.save(update_fields=["plan"])
    monkeypatch.setattr(
        "apps.agent.workflow_reports.render_report",
        lambda *args: b"# Model interpretation\n",
    )
    revised = generate_report(workflow, env["owner"], env["policy"])
    revised_path, _, _ = _paths(workflow)
    assert revised["checksum"] != original["checksum"] and revised_path != original_path
    assert "interpretation-1" in str(revised_path)
    assert (original_path.read_bytes(), metadata_path.read_bytes()) == before
    imported = import_report(workflow, env["owner"], env["policy"])
    assert DataResource.objects.get(pk=imported["resourceId"]).source.endswith(
        ":interpretation-1"
    )


def test_report_real_content_persistent_idempotent_and_no_private_model_payload(
    completed,
):
    env = completed
    before_hash = env["workflow"].plan_hash
    response = request(env)
    assert response.status_code == 200, response.content
    data = response.json()
    assert data["contentType"] == "text/markdown"
    assert data["fileName"].endswith(".md")
    assert data["resourceId"] is None
    assert data["canDownload"] and data["canImport"]
    repeated = request(env)
    assert repeated.json() == data
    preview = request(env, "preview/", "get")
    assert preview.status_code == 200, preview.content
    content = preview.json()["content"]
    for expected in (
        "优先调查 A 区",
        "A | -0.2 | 调查",
        "第 2 页",
        "输入质量通过",
        "statistics.csv",
        "1.0.0",
    ):
        assert expected in content
    assert "SECRET_" not in content
    assert not preview.json()["truncated"]
    path, metadata_path, _ = _paths(env["workflow"])
    assert path.read_text(encoding="utf-8") == content
    assert checksum(path) == data["checksum"]
    assert "SECRET_" not in metadata_path.read_text(encoding="utf-8")
    assert ComputeTask.objects.count() == 1
    env["workflow"].refresh_from_db()
    assert env["workflow"].plan_hash == before_hash


def test_report_download_real_utf8_file_and_export_permission(completed):
    env = completed
    assert request(env).status_code == 200
    response = request(env, "download/", "get")
    assert response.status_code == 200
    assert response["Content-Type"] == "text/markdown; charset=utf-8"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "attachment;" in response["Content-Disposition"]
    assert "# 生态风险分析报告" in b"".join(response.streaming_content).decode("utf-8")
    env["owner"].user_permissions.remove(
        Permission.objects.get(codename="export_dataresource")
    )
    assert request(env, "download/", "get").status_code == 403
    assert request(env, "preview/", "get").status_code == 200
    assert request(env).json()["canDownload"] is False


def test_saved_report_remains_readable_after_metadata_and_knowledge_updates(completed):
    env = completed
    first = request(env)
    assert first.status_code == 200, first.content
    content = request(env, "preview/", "get").json()["content"]
    resource = env["resource"]
    resource.name = "修改后的数据名称"
    resource.save()
    knowledge = env["knowledge"]
    knowledge.revision += 1
    knowledge.save(update_fields=["revision"])
    assert request(env).json() == first.json()
    preview = request(env, "preview/", "get")
    assert preview.status_code == 200 and preview.json()["content"] == content
    assert request(env, "download/", "get").status_code == 200
    assert request(env, "import/").status_code == 403
    knowledge.status = "draft"
    knowledge.save(update_fields=["status"])
    assert request(env, "preview/", "get").status_code == 403


def test_generating_a_new_report_still_requires_current_frozen_knowledge(completed):
    env = completed
    knowledge = env["knowledge"]
    knowledge.revision += 1
    knowledge.save(update_fields=["revision"])
    assert request(env).status_code == 403
    path, metadata_path, _ = _paths(env["workflow"])
    assert not path.exists() and not metadata_path.exists()


@pytest.mark.django_db(transaction=True)
def test_saved_report_reads_confirmed_deleted_stage_result(completed):
    from apps.agent.workflow_reports import authorize_context
    from apps.compute.models import ComputeImport
    from apps.core.storage import table_data_path

    env = completed
    env["owner"].user_permissions.add(
        Permission.objects.get(codename="delete_dataresource")
    )
    result_file = table_data_path("history-stage/statistics.csv")
    result_file.parent.mkdir(parents=True)
    result_file.write_bytes(app_path(env["output"].path).read_bytes())
    resource = DataResource.objects.create(
        name="调查统计",
        code="history-report-stage",
        data_type="table",
        file_format="CSV",
        storage_path="table/history-stage/statistics.csv",
        is_compute_result=True,
    )
    ComputeImport.objects.create(
        output=env["output"],
        requested_by=env["owner"],
        name=resource.name,
        status="ready",
        resource=resource,
    )
    workflow = env["workflow"]
    workflow.result_resource_ids = [resource.id]
    workflow.plan["stages"][0]["outputs"] = [{"resourceId": resource.id}]
    workflow.save(update_fields=["result_resource_ids", "plan"])
    assert request(env).status_code == 200
    original = request(env, "preview/", "get").json()["content"]
    header = {"HTTP_X_PROJECT_ID": str(env["project"].id)}
    selection = {"resourceIds": [resource.id]}
    preview = env["client"].post(
        "/api/catalog/resources/delete-preview/",
        json.dumps(selection),
        content_type="application/json",
        **header,
    )
    assert preview.status_code == 200, preview.content
    deleted = env["client"].post(
        "/api/catalog/resources/delete/",
        json.dumps(
            {
                **selection,
                "confirmed": True,
                "historyConfirmationToken": preview.json()["confirmationToken"],
            }
        ),
        content_type="application/json",
        **header,
    )
    assert deleted.json()["deletedCount"] == 1, deleted.content
    workflow.refresh_from_db()
    # Frozen legacy result lists may retain an ID even after the deletion receipt.
    workflow.result_resource_ids = [resource.id]
    workflow.save(update_fields=["result_resource_ids"])
    authorize_context(workflow, env["owner"], env["policy"], history=True)
    assert request(env).status_code == 200
    assert request(env, "preview/", "get").json()["content"] == original
    download = request(env, "download/", "get")
    assert download.status_code == 200
    assert b"".join(download.streaming_content).decode("utf-8") == original
    assert request(env, "import/").status_code == 403


def test_report_import_document_compute_result_private_and_idempotent(completed):
    env = completed
    assert request(env).status_code == 200
    response = request(env, "import/")
    assert response.status_code == 200, response.content
    data = response.json()
    resource = DataResource.objects.get(pk=data["resourceId"])
    assert resource.data_type == "document" and resource.file_format == "MD"
    assert resource.is_compute_result and resource.owner_only
    assert resource.maintainer_id == env["owner"].id
    assert resource.project_tag_id == env["project"].id
    assert resource.storage_path.endswith("/report.md")
    assert "/ 数据资源 / 计算结果 /" in data["resourceLocation"]
    count = DataResource.objects.count()
    assert request(env, "import/").json() == data
    assert DataResource.objects.count() == count
    assert request(env).json()["resourceId"] == resource.id


def test_report_import_requires_a_saved_report(completed):
    before = DataResource.objects.count()
    assert request(completed, "import/").status_code == 404
    assert DataResource.objects.count() == before
    path, metadata_path, _ = _paths(completed["workflow"])
    assert not path.exists() and not metadata_path.exists()


def test_report_import_requires_add_permission(completed):
    env = completed
    env["owner"].user_permissions.remove(
        Permission.objects.get(codename="add_dataresource")
    )
    assert request(env, "import/").status_code == 403
    response = request(env)
    assert response.status_code == 200
    assert response.json()["canImport"] is False


@pytest.mark.parametrize(
    "status",
    ["queued", "waiting_compute", "waiting_approval", "paused", "failed", "cancelled"],
)
def test_report_only_completed_workflows(completed, status):
    env = completed
    AgentWorkflow.objects.filter(pk=env["workflow"].id).update(status=status)
    assert request(env).status_code == 409
    assert not _paths(env["workflow"])[0].exists()


def test_report_owner_and_current_project_required(completed):
    env = completed
    env["client"].force_login(env["admin"])
    assert request(env).status_code == 404
    env["client"].force_login(env["owner"])
    response = env["client"].post(
        f"/api/agent/workflows/{env['workflow'].id}/report/",
        data="{}",
        content_type="application/json",
        HTTP_X_PROJECT_ID="1",
    )
    assert response.status_code == 404


@pytest.mark.parametrize("source", ["input", "knowledge", "report", "output_resource"])
def test_report_rechecks_revoked_sources_after_generation(completed, source):
    from apps.compute.models import ComputeImport

    env = completed
    assert request(env).status_code == 200
    if source == "input":
        DataResource.objects.filter(pk=env["resource"].id).update(
            owner_only=True, maintainer=env["outsider"]
        )
    elif source == "knowledge":
        KnowledgeEntry.objects.filter(pk=env["knowledge"].id).update(status="draft")
    elif source == "report":
        imported = request(env, "import/").json()["resourceId"]
        DataResource.objects.filter(pk=imported).update(
            owner_only=True, maintainer=env["outsider"]
        )
    else:
        resource = DataResource.objects.create(
            name="被撤权的成果",
            code="revoked-output",
            data_type="table",
            owner_only=True,
            maintainer=env["outsider"],
        )
        ComputeImport.objects.create(
            output=env["output"],
            requested_by=env["owner"],
            name="统计结果",
            status="ready",
            resource=resource,
        )
    for suffix, method in (
        ("", "post"),
        ("preview/", "get"),
        ("download/", "get"),
        ("import/", "post"),
    ):
        assert request(env, suffix, method).status_code == 403


def test_report_tamper_detected_and_not_regenerated(completed):
    env = completed
    assert request(env).status_code == 200
    path, _, _ = _paths(env["workflow"])
    path.write_bytes(b"tampered report")
    for suffix, method in (
        ("", "post"),
        ("preview/", "get"),
        ("download/", "get"),
        ("import/", "post"),
    ):
        assert request(env, suffix, method).status_code == 409
    assert path.read_bytes() == b"tampered report"


def test_report_missing_or_unknown_results(completed):
    env = completed
    assert request(env, "preview/", "get").status_code == 404
    assert request(env, "download/", "get").status_code == 404
    AgentWorkflow.objects.filter(pk=env["workflow"].id).update(result_ids=[999999])
    assert request(env).status_code == 403


def test_report_content_checks_actual_statistics_checksum(completed):
    env = completed
    app_path(env["output"].path).write_text("region,value\nA,999\n", encoding="utf-8")
    assert request(env).status_code == 409
    assert not _paths(env["workflow"])[0].exists()


def test_report_rejects_undeclared_body_fields(completed):
    assert request(completed, body={"force": True}).status_code == 400
