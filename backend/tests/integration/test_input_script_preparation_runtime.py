"""Generated preparation code uses the real queue, imports and control gates."""

import io
import json
from pathlib import Path
import runpy
from uuid import uuid4
from unittest.mock import Mock

import pytest
from django.core.files.uploadedfile import UploadedFile
from django.core.exceptions import PermissionDenied

from apps.agent import input_script_model
from apps.business_flows import catalog, runtime
from apps.business_flows.builtins import source_summary_definition
from apps.business_flows.input_preparation import advance_inputs
from apps.business_flows.script_api import detail, clarify
from apps.business_flows.state import state
from apps.compute.models import (
    AlgorithmResource,
    ComputeTask,
    ComputeOutput,
    ComputeImport,
)
from apps.compute.views import store_version
from apps.compute.data import inspect_output
from apps.compute.packages import checksum
from apps.compute.quality import quality_metadata
from apps.compute.worker import process_import, task_scope
from apps.core.storage import app_path
from apps.projects.context import ProjectScope, project_scope
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_business_flow_operator_runtime import operators  # noqa: F401

# ruff: noqa: F811
pytestmark = pytest.mark.efficiency
ROOT = Path(__file__).resolve().parents[3]
CODE = 'import pandas as pd\ndef run(context):\n    data = pd.read_csv(context.input_path("source_table_1"))\n    data.rename(columns={"value":"converted_value"}).to_csv(context.output_path("prepared.csv"),index=False)\n'


@pytest.fixture
def scripts(operators, monkeypatch):
    env = operators
    builder = runpy.run_path(str(ROOT / "examples/compute/data-script-bridge/build.py"))
    raw = builder["build"]()
    with project_scope(ProjectScope((1,), 1, env["admin"].pk, True)):
        algorithm = AlgorithmResource.objects.create(
            identifier="input-data-script-bridge",
            name="数据衔接脚本",
            created_by=env["admin"],
        )
        bridge = store_version(
            algorithm, UploadedFile(io.BytesIO(raw), name="operator.zip", size=len(raw))
        )
        bridge.status, bridge.runtime_digest = "published", "sha256:" + "a" * 64
        bridge.save()
    monkeypatch.setattr(
        "apps.business_flows.script_bridges.script_isolation_status",
        lambda: {"available": True},
    )
    spec = source_summary_definition()
    spec["inputRequirements"][0]["requiredFields"] = ["converted_value"]
    with project_scope(env["scope"]):
        _, version = catalog.register_flow(
            env["admin"],
            {
                "code": "script-" + uuid4().hex[:8],
                "name": "资料格式衔接",
                "definition": spec,
            },
        )
        workflow = runtime.start_flow(
            env["owner"],
            version,
            {
                "model": "mock",
                "inputs": {"source": env["resource"].pk},
                "idempotencyKey": uuid4().hex,
            },
        )
    calls = []

    def generate(workflow, node, attempt, evidence, **kwargs):
        calls.append({"attempt": attempt, "evidence": evidence})
        audit = {
            "requestId": uuid4().hex,
            "status": "requesting",
            "modelAlias": "mock",
            "role": "executor",
            "requested": True,
        }
        kwargs["callbacks"]["on_record"](audit)
        return {
            "decision": "script",
            "code": CODE,
            "targetType": "table",
            "summary": "按真实字段生成工作副本",
            "question": "",
            "evidenceIds": [item["id"] for item in evidence],
            "audit": audit,
        }

    monkeypatch.setattr(input_script_model, "generate", generate)
    return {**env, "bridge": bridge, "workflow": workflow, "calls": calls}


def advance(env):
    workflow = env["workflow"]
    workflow.refresh_from_db()
    with project_scope(env["scope"]):
        policy = runtime.authorize(env["owner"], workflow)
        return advance_inputs(workflow, env["owner"], policy)


def finish(env):
    with project_scope(env["scope"]):
        task = ComputeTask.objects.get()
        task.status = "succeeded"
        task.save(update_fields=["status"])
        path = app_path(
            "projects",
            str(task.project_tag_id),
            "compute",
            "outputs",
            str(task.pk),
            "prepared.csv",
        )
        path.parent.mkdir(parents=True)
        path.write_text("region,converted_value\nA,2\nA,4\nB,8\n")
        contract = json.loads(task.parameters["target_contract"])
        metadata = inspect_output(path, "table", contract=contract)
        metadata.update(
            quality_metadata(
                {
                    "version": 1,
                    "status": "passed",
                    "summary": "队列回归的实际CSV结果",
                    "metrics": {},
                    "knowledgeFacts": {},
                }
            )
        )
        return ComputeOutput.objects.create(
            task=task,
            key="prepared_table",
            label="衔接结果",
            kind="table",
            file_name="prepared.csv",
            path=path.relative_to(app_path()).as_posix(),
            size_bytes=path.stat().st_size,
            checksum=checksum(path),
            metadata=metadata,
        )


def test_agent_script_is_submitted_once_and_code_is_loaded_only_on_demand(scripts):
    env = scripts
    assert advance(env) is False
    assert advance(env) is False
    assert len(env["calls"]) == 1
    with project_scope(env["scope"]):
        task = ComputeTask.objects.get()
        assert task.parameters["code"] == CODE and task.version_id == env["bridge"].pk
        assert task.input_records.get().resource_id == env["resource"].pk
        run = runtime.serialize_run(env["owner"], env["workflow"])
        assert "code" not in json.dumps(run, ensure_ascii=False)
        assert detail(env["owner"], env["workflow"], "source")["code"] == CODE
    output = finish(env)
    assert advance(env) is False
    with project_scope(env["scope"]):
        record = ComputeImport.objects.get(output=output)
        with task_scope(output.task):
            process_import(record)
        record.refresh_from_db()
        assert record.status == "ready", record.error
    assert advance(env) is True
    assert len(env["calls"]) == 1
    assert env["workflow"].plan["inputs"]["source"] == record.resource_id
    env["resource"].refresh_from_db()
    assert env["resource"].storage_path == "samples"


def test_real_failed_attempt_feedback_reaches_the_same_preparation_task(scripts):
    env = scripts
    assert advance(env) is False
    with project_scope(env["scope"]):
        first = ComputeTask.objects.get()
        first.status, first.error = (
            "failed",
            '适配脚本执行失败：{"errorType":"KeyError","message":"value","line":3}',
        )
        first.save(update_fields=["status", "error"])
    assert advance(env) is False
    assert advance(env) is False
    with project_scope(env["scope"]):
        assert ComputeTask.objects.count() == 2
        assert detail(env["owner"], env["workflow"], "source", 1)["status"] == "failed"
        assert detail(env["owner"], env["workflow"], "source", 2)["code"] == CODE
    assert [call["attempt"] for call in env["calls"]] == [1, 2]


def test_source_revocation_and_cancel_block_script_generation(scripts):
    env = scripts
    env["resource"].owner_only, env["resource"].maintainer = True, env["outsider"]
    env["resource"].save(update_fields=["owner_only", "maintainer"])
    with pytest.raises(PermissionDenied):
        advance(env)
    assert env["calls"] == []
    with project_scope(env["scope"]):
        assert not ComputeTask.objects.exists()
        runtime.control_flow(env["owner"], env["workflow"], "cancel")


def test_clarification_is_not_a_scientific_approval_and_does_not_repeat_models(
    scripts, monkeypatch
):
    env = scripts

    def question(workflow, node, attempt, evidence, **kwargs):
        return {
            "decision": "needs_clarification",
            "code": "",
            "targetType": "table",
            "summary": "需明确字段",
            "question": "哪个字段表示观测值？",
            "evidenceIds": [item["id"] for item in evidence],
            "audit": {},
        }

    ask = Mock(side_effect=question)
    monkeypatch.setattr(input_script_model, "generate", ask)
    assert advance(env) is False
    assert advance(env) is False
    assert ask.call_count == 1
    workflow = env["workflow"]
    with project_scope(env["scope"]):
        before = dict(state(workflow)["nodes"]["summarize"]["human"])
        body = {
            "role": "source",
            "feedback": "value字段",
            "revision": state(workflow)["revision"],
            "idempotencyKey": uuid4().hex,
        }
        current = clarify(env["owner"], workflow, body)
        assert current.status == "queued"
        assert state(current)["nodes"]["summarize"]["human"] == before
        assert clarify(env["owner"], current, body).pk == current.pk
        assert not ComputeTask.objects.exists()
