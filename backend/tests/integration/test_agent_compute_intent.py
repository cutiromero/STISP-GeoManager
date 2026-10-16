"""Real task binding, interactive parameters and deterministic chat execution."""

import io
import json
from unittest.mock import patch

import numpy as np
import pytest
import rasterio
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from rasterio.transform import from_origin

from apps.agent.compute_intents import process, update, serialize, report
from apps.agent.compute_intent_text import explicit_parameters
from apps.agent.models import AgentPolicy, AgentRun, Conversation, AgentComputeFollowup
from apps.agent.policy import default_policy
from apps.agent.tools import execute
from apps.compute.models import (
    AlgorithmResource,
    ComputeTask,
    ComputeOutput,
    ComputeImport,
)
from apps.compute.templates import build_package
from apps.compute.views import store_version
from apps.core.storage import raster_source_path
from apps.projects.context import ProjectScope, project_scope
from apps.raster.models import RasterDataset
from tests.integration.test_compute import setup_compute  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def env(setup_compute, settings):  # noqa: F811
    env = setup_compute
    settings.AGENT_MODELS = [
        {
            "alias": "mock",
            "name": "Mock",
            "base_url": "http://127.0.0.1:19100/v1",
            "model_id": "mock",
            "agent": True,
        }
    ]
    env["owner"].user_permissions.add(
        *Permission.objects.filter(
            codename__in=["use_local_model", "use_data_agent", "query_data"]
        )
    )
    policy = default_policy()
    policy["operatorEnabled"] = True
    AgentPolicy.objects.create(value=policy)
    env["policy"] = policy
    with project_scope(ProjectScope((1,), 1, env["admin"].id, True)):
        for template, key in [(4, "ndvi"), (5, "ndwi")]:
            package, identifier = build_package(template)
            algorithm = AlgorithmResource.objects.create(
                identifier=identifier, name=key.upper(), created_by=env["admin"]
            )
            version = store_version(
                algorithm,
                UploadedFile(
                    io.BytesIO(package), name="operator.zip", size=len(package)
                ),
            )
            version.status, version.runtime_digest = "published", "sha256:" + "a" * 64
            version.save()
            env[key] = version
    env["scope"] = ProjectScope(
        (env["project"].id,), env["project"].id, env["owner"].id
    )
    with project_scope(env["scope"]):
        from apps.catalog.models import DataResource

        path = raster_source_path("intent.tif")
        path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=4,
            height=4,
            count=8,
            dtype="uint8",
            crs="EPSG:32645",
            transform=from_origin(615000, 4440000, 10, 10),
        ) as dst:
            dst.write(np.full((8, 4, 4), 120, dtype="uint8"))
        env["raster"] = DataResource.objects.create(
            name="八波段试验影像",
            code="intent-raster",
            data_type="raster",
            file_format="GTIFF",
            size_bytes=path.stat().st_size,
        )
        RasterDataset.objects.create(
            name="八波段试验影像",
            code="intent-raster",
            source_relative_path="intent.tif",
            data_resource=env["raster"],
            status="ready",
        )
        env["conversation"] = Conversation.objects.create(
            owner=env["owner"], mode="agent"
        )
        yield env


def run(env, prompt, selected=True):
    return AgentRun.objects.create(
        conversation=env["conversation"],
        owner=env["owner"],
        model="mock",
        prompt=prompt,
        idempotency_key="intent-" + str(env["conversation"].runs.count()),
        resource_ids=[env["raster"].id] if selected else [],
        status="succeeded",
    )


def request(env, item, body):
    return env["client"].post(
        f"/api/agent/runs/{item.id}/compute-intent/",
        json.dumps(body),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )


@pytest.mark.parametrize(
    "prompt",
    [
        "计算NDVI，red=3 nir=8",
        "计算NDVI，红光波段 = 第 3 波段，近红外波段 = 第 8 波段",
        "计算NDVI，我记得第三波段是红，第8波段是红外",
        "NDVI 红光是3，近红外是8",
    ],
)
def test_explicit_bands_from_user_message(env, prompt):
    values, conflicts = explicit_parameters(prompt, env["ndvi"].manifest)
    assert values == {"red": 3, "nir": 8}
    assert not conflicts


def test_conflicting_bands_are_not_confirmation(env):
    values, conflicts = explicit_parameters("red=3 red=5 nir=8", env["ndvi"].manifest)
    assert values == {"nir": 8}
    assert conflicts == ["red"]


def test_missing_bands_generate_manifest_form_without_default_confirmation(env):
    item = run(env, "使用NDWI算法对影像处理，结果入库")
    with patch("apps.agent.compute_intents.record_tool", return_value=({}, [])):
        answer = process(item, env["owner"], env["policy"])
    assert "选择" in answer
    assert item.compute_intent["status"] == "collecting"
    assert item.compute_intent["parameters"] == {}
    assert item.compute_intent["missingParameters"] == ["green", "nir"]
    assert item.compute_intent["autoImport"] is True
    assert not ComputeTask.objects.exists()
    dto = serialize(item, env["owner"], env["policy"])
    assert dto["algorithm"]["manifest"] == env["ndwi"].manifest
    assert any(
        candidate["id"] == env["raster"].id and candidate["bands"] == 8
        for candidate in dto["inputCandidates"]
    )


def test_text_bands_submit_real_task_without_model_and_never_use_old_task(env):
    item = run(env, "计算这个图片的NDVI，我记得第三波段是红，第8波段是红外")
    process(item, env["owner"], env["policy"])
    task = ComputeTask.objects.get()
    assert task.parameters == {"red": 3, "nir": 8}
    assert item.compute_intent["taskId"] == str(task.id)
    assert AgentComputeFollowup.objects.get(task=task).run == item
    assert not ComputeImport.objects.exists()
    assert str(task.id) not in report(item, env["owner"], env["policy"])


def test_ndwi_to_ndvi_replaces_only_pending_plan(env):
    previous = run(env, "使用NDWI处理影像")
    process(previous, env["owner"], env["policy"])
    item = run(env, "计算这个图片的NDVI，第三波段是红，第8波段是红外", selected=False)
    process(item, env["owner"], env["policy"])
    previous.refresh_from_db()
    assert previous.compute_intent["status"] == "superseded"
    assert ComputeTask.objects.get().version == env["ndvi"]
    assert ComputeTask.objects.get().parameters == {"red": 3, "nir": 8}


def test_short_band_reply_continues_current_plan_without_sensor_question(env):
    previous = run(env, "计算NDVI")
    process(previous, env["owner"], env["policy"])
    item = run(env, "对啊，就是红光波段=第3波段，近红外波段=第8波段", selected=False)
    answer = process(item, env["owner"], env["policy"])
    assert "已提交" in answer
    assert "传感器" not in answer
    assert ComputeTask.objects.get().parameters == {"red": 3, "nir": 8}


def test_form_submit_is_idempotent_and_stale_revision_rejected(env):
    item = run(env, "计算NDVI")
    process(item, env["owner"], env["policy"])
    revision = item.compute_intent["planRevision"]
    response = request(
        env,
        item,
        {
            "action": "submit",
            "planRevision": revision,
            "parameters": {"red": 3, "nir": 8},
        },
    )
    assert response.status_code == 200, response.content
    intent = response.json()["computeIntent"]
    repeated = request(
        env, item, {"action": "submit", "planRevision": intent["planRevision"]}
    )
    assert repeated.status_code == 200, repeated.content
    assert ComputeTask.objects.count() == 1
    stale = request(env, item, {"action": "submit", "planRevision": revision})
    assert stale.status_code == 409


def test_changed_input_rejects_submit_and_keeps_original_data(env):
    item = run(env, "计算NDVI")
    process(item, env["owner"], env["policy"])
    env["raster"].description = "人工修改了元信息"
    env["raster"].save()
    response = request(
        env,
        item,
        {
            "action": "submit",
            "planRevision": item.compute_intent["planRevision"],
            "parameters": {"red": 3, "nir": 8},
        },
    )
    assert response.status_code == 400 and "已变化" in response.json()["detail"]
    assert not ComputeTask.objects.exists()


def test_other_owner_cross_project_archived_cancelled_and_superseded(env):
    item = run(env, "计算NDVI")
    process(item, env["owner"], env["policy"])
    env["client"].force_login(env["outsider"])
    assert (
        request(
            env,
            item,
            {"action": "submit", "planRevision": item.compute_intent["planRevision"]},
        ).status_code
        == 404
    )
    env["client"].force_login(env["owner"])
    response = env["client"].get(
        f"/api/agent/runs/{item.id}/compute-intent/", HTTP_X_PROJECT_ID="1"
    )
    assert response.status_code == 404
    item.cancel_requested = True
    item.save()
    assert (
        request(
            env,
            item,
            {"action": "submit", "planRevision": item.compute_intent["planRevision"]},
        ).status_code
        == 409
    )


def test_band_out_of_bounds_and_unregistered_parameters_rejected(env):
    item = run(env, "计算NDVI")
    process(item, env["owner"], env["policy"])
    for parameters in [
        {"red": 99, "nir": 8},
        {"red": 3, "nir": 8, "shell": "anything"},
    ]:
        response = request(
            env,
            item,
            {
                "action": "submit",
                "planRevision": item.compute_intent["planRevision"],
                "parameters": parameters,
            },
        )
        assert response.status_code == 400
    assert not ComputeTask.objects.exists()


def test_followup_never_guesses_an_unrelated_old_task(env):
    from apps.compute.services import submit

    unrelated = submit(env["owner"], env["body"])
    item = run(env, "跑完了没", selected=False)
    answer = process(item, env["owner"], env["policy"])
    assert "还没有实际提交" in answer
    assert not item.evidence
    assert str(unrelated.id) not in answer


def test_followup_reports_real_task_and_explicit_manual_import(env):
    item = run(env, "计算NDVI，red=3 nir=8")
    process(item, env["owner"], env["policy"])
    task = ComputeTask.objects.get()
    task.status = "succeeded"
    task.save()
    output = ComputeOutput.objects.create(
        task=task,
        key="ndvi",
        label="NDVI结果",
        kind="raster",
        file_name="ndvi.tif",
        path="unused.tif",
        size_bytes=3,
        checksum="a" * 64,
    )
    followup = run(env, "跑完了没", selected=False)
    assert "计算完成" in process(followup, env["owner"], env["policy"])
    assert not ComputeImport.objects.exists()
    importer = run(env, "入库", selected=False)
    assert "正在入库" in process(importer, env["owner"], env["policy"])
    record = ComputeImport.objects.get(output=output)
    record.status, record.resource = "ready", env["raster"]
    record.save()
    from apps.agent.compute_tools import resume_followups

    resume_followups()
    locator = run(env, "结果在哪", selected=False)
    answer = process(locator, env["owner"], env["policy"])
    assert env["project"].name in answer and env["raster"].name in answer
    assert str(task.id) not in answer


def test_model_cannot_submit_default_bands_without_user_confirmation(env):
    item = run(env, "请分析这张影像")
    result, _ = execute(
        item,
        "execute_operator",
        {
            "versionId": env["ndvi"].id,
            "inputs": {"image": env["raster"].id},
            "parameters": {"red": 1, "nir": 2},
        },
    )
    assert result["needsInput"] is True
    assert not ComputeTask.objects.exists()


def test_knowledge_question_does_not_start_computation(env):
    item = run(env, "NDVI是什么，请介绍算法")
    assert process(item, env["owner"], env["policy"]) is None
    assert not ComputeTask.objects.exists()


def test_generic_manifest_field_form_works_without_ndvi_special_page(env):
    item = run(env, "使用表格统计进行计算", selected=False)
    item.resource_ids = [env["resource"].id]
    item.save()
    process(item, env["owner"], env["policy"])
    assert item.compute_intent["missingParameters"] == ["group", "value"]
    update(
        item,
        env["owner"],
        env["policy"],
        {
            "action": "submit",
            "planRevision": item.compute_intent["planRevision"],
            "parameters": {"group": "region", "value": "value", "method": "mean"},
        },
    )
    assert ComputeTask.objects.get().version == env["version"]


@pytest.mark.parametrize(
    "claim",
    ["任务已提交，计算已完成", "算好了", "成功完成", "已生成结果", "已保存到数据库"],
)
def test_model_false_success_is_replaced_by_platform_evidence(env, claim):
    from apps.agent.worker import append_compute_status

    item = run(env, "计算NDVI")
    answer = append_compute_status(claim, item, env["owner"], env["policy"])
    assert "没有实际提交" in answer


def test_explicit_bands_use_model_and_wait_for_real_compute(env, monkeypatch):
    from apps.agent.worker import run_task
    from tests.integration.test_agent_interactions import mock_model

    item = run(env, "计算NDVI，red=3 nir=8")
    item.status = "running"
    item.save()
    requests = []
    mock_model(
        monkeypatch,
        [
            {
                "action": "execute_operator",
                "arguments": {
                    "versionId": env["ndvi"].id,
                    "inputs": {"image": env["raster"].id},
                    "parameters": {"red": 3, "nir": 8},
                },
            }
        ],
        requests,
    )
    run_task(item.id)
    item.refresh_from_db()
    assert requests and item.status == "waiting_compute"
    assert ComputeTask.objects.count() == 1
    assert ComputeTask.objects.get().parameters == {"red": 3, "nir": 8}
    assert not item.interaction_history


def test_model_cannot_change_already_confirmed_bands(env):
    item = run(env, "计算NDVI")
    process(item, env["owner"], env["policy"])
    update(
        item,
        env["owner"],
        env["policy"],
        {
            "action": "update",
            "planRevision": item.compute_intent["planRevision"],
            "parameters": {"red": 3, "nir": 8},
        },
    )
    assert item.compute_intent["status"] == "ready"
    with pytest.raises(ValidationError, match="明确选择"):
        execute(
            item,
            "execute_operator",
            {
                "versionId": env["ndvi"].id,
                "inputs": {"image": env["raster"].id},
                "parameters": {"red": 1, "nir": 2},
            },
        )
    assert not ComputeTask.objects.exists()


def test_queued_task_with_fake_ready_metadata_is_not_completion(env):
    item = run(env, "计算NDVI，red=3 nir=8")
    process(item, env["owner"], env["policy"])
    task = ComputeTask.objects.get()
    output = ComputeOutput.objects.create(
        task=task,
        key="ndvi",
        label="伪状态测试",
        kind="raster",
        file_name="ndvi.tif",
        path="unused.tif",
        size_bytes=3,
        checksum="a" * 64,
    )
    ComputeImport.objects.create(
        output=output,
        requested_by=env["owner"],
        name="伪状态测试",
        status="ready",
        resource=env["raster"],
    )
    answer = report(item, env["owner"], env["policy"])
    assert (
        "已提交" in answer and "已保存至" not in answer and "计算完成。" not in answer
    )


def test_no_silent_reuse_of_unrelated_historical_resource(env):
    run(env, "此前的另一张影像")
    item = run(env, "计算NDVI，red=3 nir=8", selected=False)
    process(item, env["owner"], env["policy"])
    assert item.compute_intent["missingInputs"] == ["image"]
    assert not ComputeTask.objects.exists()


def test_candidate_metadata_is_reused_on_poll_after_authorization(env):
    item = run(env, "计算NDVI")
    process(item, env["owner"], env["policy"])
    from apps.agent.compute_intents import _candidate, candidate

    _candidate.cache_clear()
    with patch("apps.agent.compute_intents.candidate", wraps=candidate) as reader:
        serialize(item, env["owner"], env["policy"])
        first_reads = reader.call_count
        serialize(item, env["owner"], env["policy"])
    assert first_reads <= 11 and reader.call_count == first_reads


def test_compute_intent_database_default_supports_old_application_insert(env):
    from django.db import connection

    item = run(env, "旧版本写入")
    columns = [
        field.column
        for field in AgentRun._meta.local_fields
        if field.name not in {"id", "compute_intent"}
    ]
    expressions = [
        "%s" if column == "idempotency_key" else connection.ops.quote_name(column)
        for column in columns
    ]
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO agent_agentrun ({', '.join(connection.ops.quote_name(column) for column in columns)}) SELECT {', '.join(expressions)} FROM agent_agentrun WHERE id=%s",
            ["legacy-compute-intent", item.id],
        )
    assert (
        AgentRun.objects.get(idempotency_key="legacy-compute-intent").compute_intent
        == {}
    )


def test_model_cannot_enable_auto_import_without_user_choice(env):
    item = run(env, "计算NDVI")
    process(item, env["owner"], env["policy"])
    update(
        item,
        env["owner"],
        env["policy"],
        {
            "action": "update",
            "planRevision": item.compute_intent["planRevision"],
            "parameters": {"red": 3, "nir": 8},
        },
    )
    with pytest.raises(ValidationError, match="明确选择"):
        execute(
            item,
            "execute_operator",
            {
                "versionId": env["ndvi"].id,
                "inputs": {"image": env["raster"].id},
                "parameters": {"red": 3, "nir": 8},
                "autoImport": True,
            },
        )
    assert not ComputeTask.objects.exists()


def test_explicit_auto_import_survives_short_band_reply(env):
    previous = run(env, "计算NDVI，完成后自动入库")
    process(previous, env["owner"], env["policy"])
    item = run(env, "对啊，红光=3，近红外=8", selected=False)
    process(item, env["owner"], env["policy"])
    assert AgentComputeFollowup.objects.get().auto_import is True


def test_algorithm_tool_retry_preserves_real_task_and_choice(env):
    item = run(env, "计算NDVI red=3 nir=8")
    process(item, env["owner"], env["policy"])
    original = item.compute_intent["taskId"]
    result, _ = execute(
        item,
        "execute_operator",
        {
            "versionId": env["ndvi"].id,
            "inputs": {"image": env["raster"].id},
            "parameters": {"red": 3, "nir": 8},
            "name": "模型更改名字",
        },
    )
    assert result["taskId"] == original
    assert item.compute_intent["taskId"] == original
    assert ComputeTask.objects.count() == 1
