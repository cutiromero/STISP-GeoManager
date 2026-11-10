"""用上传用七份原始资料、真实算子与正常确认接口验收七节点。"""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time
from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.agent import demo_workflow, provider
from apps.agent.workflow import run_workflow, resume_waiting
from apps.agent.workflow_uploads import store_upload
from apps.business_flows import catalog, legacy, runtime
from apps.business_flows.builtins import builtin_flows
from apps.compute.data import candidate
from apps.compute.models import ComputeImport, ComputeTask, RuntimeLease
from apps.compute.worker import process_import
from apps.projects.context import ProjectScope, project_scope
from tests.integration.test_logic_flow_budget_audit import conservative_tokens
from tests.integration.test_logic_reasoning_journey import (
    native_task,
    post,
    register_operators,
    register_rules,
)
from tests.unit.test_geology_multi_algorithms import fixture

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT.parent / "逻辑推理测试数据_按草案" / "上传用"
DATA_ROOT = ROOT.parent / "GeoManagerData-logic-qa"
OUTPUT = ROOT / ".runtime" / "task-h" / "local-e2e"
INPUTS = {
    "lithology": "海德乌拉_模拟识别岩性图.gpkg",
    "faults": "示范区构造_模拟识别.gpkg",
    "hematite": "chitiekuang_rasterized.tif",
    "chlorite": "lvnishi_rasterized.tif",
    "hydromica": "shuiyunmu_rasterized.tif",
    "calcite": "fangjieshi_rasterized.tif",
    "dolomite": "baiyunshi_rasterized.tif",
}
MAX_TICKS = 100
WINDOW = 32768

pytestmark = pytest.mark.django_db
pytest_plugins = ["tests.integration.test_generic_chat"]


def test_uploaded_geology_business_flow_completes_all_seven_nodes(
    generic, tmp_path, settings, monkeypatch
):
    env = generic
    env["scope"] = ProjectScope(
        (env["project"].id,), env["project"].id, env["owner"].id
    )
    env["project"].code = "02"
    env["project"].save(update_fields=["code"])
    data_folder = DATA_ROOT / "app" / ("task_h_e2e_" + uuid4().hex)
    settings.PROJECT_CONFIG = replace(
        settings.PROJECT_CONFIG,
        app_data=data_folder,
        research_data_root=DATA_ROOT / "research",
    )
    settings.AGENT_MODELS[0] = {**settings.AGENT_MODELS[0], "qwen": True}
    monkeypatch.setattr("apps.compute.services.candidate", candidate)
    monkeypatch.setattr(provider, "model_window", lambda model: WINDOW)
    monkeypatch.setattr(provider, "count_tokens", conservative_tokens)
    monkeypatch.setattr("apps.agent.context.count_tokens", conservative_tokens)
    calls, records, approvals = [], [], []
    node_metrics = {
        key: {"started": None, "finished": None, "states": [], "modelRequests": 0}
        for key in (
            "inputs",
            "check",
            "apply",
            "recheck",
            "relations",
            "prospect",
            "finish",
        )
    }
    started = time.perf_counter()

    def observe(current):
        now = time.perf_counter() - started
        for key, value in legacy.projected_state(current)["nodes"].items():
            metric = node_metrics[key]
            status = value["status"]
            if not metric["states"] or metric["states"][-1]["status"] != status:
                metric["states"].append({"status": status, "seconds": round(now, 3)})
            if status != "pending" and metric["started"] is None:
                metric["started"] = now
            if status == "succeeded" and metric["finished"] is None:
                metric["finished"] = now

    save = demo_workflow._save
    decide = demo_workflow.decide

    def saved(current, *args, **options):
        result = save(current, *args, **options)
        observe(current)
        return result

    def deciding(current, *args, **options):
        observe(current)
        return decide(current, *args, **options)

    monkeypatch.setattr(demo_workflow, "_save", saved)
    monkeypatch.setattr(demo_workflow, "decide", deciding)

    def streamed(model, messages, maximum, guard, **options):
        guard()
        tokens = conservative_tokens(model, messages)
        assert tokens <= WINDOW - maximum - 256
        packet = json.loads(messages[1]["content"])
        metric = node_metrics[packet["node"]["id"]]
        if metric["started"] is None:
            metric["started"] = time.perf_counter() - started
        metric["modelRequests"] += 1
        calls.append(
            {"node": packet["node"]["id"], "tokens": tokens, "outputTokens": maximum}
        )
        yield json.dumps(
            {
                "decision": "accept",
                "reason": "Mock审核仅核对已提供统计；专业裁定与批准仍由用户决定",
                "issues": [],
                "repairInstructions": "",
                "evidenceIds": ["node-result"],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(provider, "stream", streamed)
    monkeypatch.setattr(
        provider,
        "model_request",
        lambda *args, **kwargs: pytest.fail("本机验收禁止连接模型服务或服务器"),
    )
    synthetic, _ = fixture(tmp_path)
    register_rules(env, synthetic)
    register_operators(env)
    identities = {}
    source_hashes = {}
    for role, filename in INPUTS.items():
        path = SOURCE / filename
        content = path.read_bytes()
        source_hashes[filename] = hashlib.sha256(content).hexdigest()
        upload = store_upload(
            env["owner"],
            env["project"].id,
            SimpleUploadedFile(filename, content),
            env["batch"],
        )
        identities[role] = upload.resource_id
    with project_scope(env["scope"]):
        _, version = catalog.register_flow(env["admin"], builtin_flows()[0])
        workflow = runtime.start_flow(
            env["owner"],
            version,
            {
                "model": "mock",
                "idempotencyKey": uuid4().hex,
                "goal": "核对上传资料并按用户批准范围完成处置、复查、构造、远景和报告",
                "inputs": identities,
                "parameters": {"uploadBatchId": env["batch"]},
            },
        )
    started = time.perf_counter()
    observe(workflow)
    for tick in range(MAX_TICKS):
        workflow.refresh_from_db()
        if workflow.status == "succeeded":
            break
        assert workflow.status not in {"failed", "interrupted", "cancelled"}, (
            workflow.detail
        )
        before = (workflow.status, workflow.current_step, workflow.plan.get("phase"))
        tick_started = time.perf_counter()
        if workflow.status == "waiting_approval":
            phase = workflow.plan["phase"]
            payload = {"planHash": workflow.plan_hash}
            if phase == "review_mapping":
                payload["fieldMapping"] = {
                    role["role"]: {
                        target["key"]: target["field"]
                        for target in role["targets"]
                        if target.get("field")
                    }
                    for role in workflow.plan["fieldMappingReview"]["roles"]
                }
            elif phase == "review_modifications":
                selected = [
                    row["id"]
                    for row in workflow.plan["modificationReview"]["suggestions"]
                    if row.get("status") == "suggested"
                ]
                payload["selectedSuggestionIds"] = selected
            else:
                assert phase in {"review_results", "review_plan"}, workflow.detail
            approvals.append(
                {
                    "phase": phase,
                    "scope": payload.get("selectedSuggestionIds", "实际展示输出或字段"),
                }
            )
            response = post(
                env, f"/api/agent/workflows/{workflow.id}/confirm/", payload
            )
            assert response.status_code == 200, response.content
        elif workflow.status == "waiting_compute":
            stage = workflow.plan["stages"][workflow.plan["stageIndex"]]
            task = ComputeTask.objects.get(pk=stage["taskId"])
            RuntimeLease.objects.filter(name="worker").update(heartbeat=timezone.now())
            if task.status == "queued":
                native_task(task)
            for record in ComputeImport.objects.filter(
                output__task=task, status="queued"
            ):
                process_import(record)
            resume_waiting()
        else:
            run_workflow(workflow.id)
        workflow.refresh_from_db()
        observe(workflow)
        records.append(
            {
                "tick": tick,
                "before": before,
                "after": (
                    workflow.status,
                    workflow.current_step,
                    workflow.plan.get("phase"),
                ),
                "seconds": round(time.perf_counter() - tick_started, 3),
                "modelRequests": len(calls),
            }
        )
    assert workflow.status == "succeeded", workflow.detail
    with project_scope(env["scope"]):
        projected = legacy.projected_state(workflow)
        assert len(projected["nodes"]) == 7
        assert all(row["status"] == "succeeded" for row in projected["nodes"].values())
    response = post(env, f"/api/agent/workflows/{workflow.id}/report/", {})
    assert response.status_code == 200, response.content
    report = response.json()
    header = {"HTTP_X_PROJECT_ID": str(env["project"].id)}
    preview = env["client"].get(report["previewUrl"], **header)
    download = env["client"].get(report["downloadUrl"], **header)
    assert preview.status_code == download.status_code == 200
    downloaded = b"".join(download.streaming_content)
    assert hashlib.sha256(downloaded).hexdigest() == report["checksum"]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "report.md").write_bytes(downloaded)
    for metric in node_metrics.values():
        assert metric["started"] is not None and metric["finished"] is not None
        metric["seconds"] = round(metric["finished"] - metric["started"], 3)
    result = {
        "workflowId": str(workflow.id),
        "status": workflow.status,
        "seconds": round(time.perf_counter() - started, 3),
        "modelRequests": calls,
        "mockDecisionCount": workflow.iteration,
        "nodes": {key: row["status"] for key, row in projected["nodes"].items()},
        "nodeMetrics": node_metrics,
        "approvals": approvals,
        "transitions": records,
        "sourceSha256": source_hashes,
        "report": report,
        "previewStatus": preview.status_code,
        "downloadStatus": download.status_code,
        "dataDirectory": str(data_folder),
        "database": "pytest隔离数据库，任务不写入正式本机业务库",
        "rules": "仓库合成试用规则；本次验证业务连通，不评估科研精度",
    }
    (OUTPUT / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "workflowId",
                    "status",
                    "seconds",
                    "nodes",
                    "previewStatus",
                    "downloadStatus",
                )
            },
            ensure_ascii=False,
        )
    )
