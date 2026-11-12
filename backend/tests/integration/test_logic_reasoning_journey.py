"""Offline conversation journey with real fixture geometry and native operators."""

import csv
import json
import runpy
import uuid
from unittest.mock import patch
from pathlib import Path

import geopandas as gpd
import pytest
import rasterio
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from shapely.geometry import LineString

from apps.agent.models import AgentRun, AgentWorkflow, Conversation, LogicConfiguration
from apps.agent.research_intents import process
from apps.agent.workflow import run_workflow, resume_waiting
from apps.agent.workflow_uploads import store_upload
from apps.catalog.models import DataResource
from apps.compute.data import candidate, freeze_input, inspect_output
from apps.compute.models import (
    AlgorithmResource,
    AlgorithmVersion,
    ComputeImport,
    ComputeOutput,
    ComputeTask,
    RuntimeLease,
)
from apps.compute.packages import checksum, validate_manifest
from apps.compute.quality import quality_metadata, read_quality_report
from apps.compute.worker import process_import
from apps.core.storage import app_path, table_data_path
from apps.knowledge.models import KnowledgeEntry
from apps.knowledge.trial_rules import SCENARIO
from tests.integration.test_generic_chat import answer
from tests.unit.test_geology_multi_algorithms import Context, fixture, load, read, store

pytestmark = pytest.mark.django_db
pytest_plugins = ["tests.integration.test_generic_chat"]
ROOT = Path(__file__).resolve().parents[3]


def post(env, url, payload):
    return env["client"].post(
        url,
        json.dumps(payload),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )


def register_rules(env, context):
    rows = read(context.inputs["rules"])
    for row in rows:
        if row["rule_id"] == "A-05":
            row["params_json"] = json.dumps({"min_area_m2": 1000})
        if row["rule_id"] == "S-01":
            row["params_json"] = json.dumps({"cover_units": ["O"], "cover_ratio": 0.8})
        if row["rule_id"] == "S-03":
            # This journey exercises an undisputed cover-line exclusion. Keep
            # nearby mapped structures inside the isolation radius so S-03 does
            # not also require a conflicting manual review for this same line.
            row["params_json"] = json.dumps(
                {**json.loads(row["params_json"]), "isolation_m": 500}
            )
        if row["rule_id"] == "P-01":
            row["params_json"] = json.dumps(
                {**json.loads(row["params_json"]), "buffer_secondary_m": 300}
            )
        if row["rule_id"] == "P-02":
            row["params_json"] = json.dumps(
                {**json.loads(row["params_json"]), "search_m": 300}
            )
        entry = KnowledgeEntry.objects.create(
            title=row["rule_id"],
            domain="geology",
            status="draft",
            statement="夹具地质规则",
            conditions=["仅本测试区"],
            exceptions=["待裁定对象保持原状"],
            sources=[{"title": "仓库合成夹具", "locator": row["rule_id"]}],
            rule_config={
                "trialScope": {
                    "scenario": SCENARIO,
                    "projectId": env["project"].id,
                    "ruleId": row["rule_id"],
                    "ruleVersion": row["rule_version"],
                },
                "parameters": json.loads(row["params_json"]),
                "rule": json.loads(row["rule_json"]),
            },
        )
        row.update(knowledge_id=entry.id, knowledge_revision=entry.revision)
    path = table_data_path("journey/rules.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    env["rules"].storage_path = "table/journey/rules.csv"
    env["rules"].file_format = "CSV"
    env["rules"].save()


def register_operators(env):
    for suffix in ("check", "apply", "relations", "prospect"):
        manifest = validate_manifest(
            json.loads(
                (
                    ROOT / f"examples/compute/geology-multi-{suffix}/operator.yaml"
                ).read_text()
            )
        )
        algorithm = AlgorithmResource.objects.create(
            identifier=manifest["identifier"],
            name=manifest["name"],
            created_by=env["owner"],
        )
        AlgorithmVersion.objects.create(
            algorithm=algorithm,
            version=manifest["version"],
            status="published",
            manifest=manifest,
            checksum="d" * 64,
            runtime_digest="sha256:" + "a" * 64,
        )
    adapter = runpy.run_path(str(ROOT / "examples/compute/input-adapters/build.py"))
    manifest = validate_manifest(adapter["manifest"]("input-raster-class-masks"))
    algorithm = AlgorithmResource.objects.create(
        identifier=manifest["identifier"],
        name=manifest["name"],
        created_by=env["owner"],
    )
    AlgorithmVersion.objects.create(
        algorithm=algorithm,
        version=manifest["version"],
        status="published",
        manifest=manifest,
        checksum="d" * 64,
        runtime_digest="sha256:" + "a" * 64,
    )


def system_references(env, context):
    roles = {}
    for role, path in context.inputs.items():
        if role == "rules":
            continue
        if path.suffix == ".gpkg":
            file = SimpleUploadedFile(
                role + ".geojson",
                gpd.read_file(path).to_crs(4326).to_json().encode(),
                "application/geo+json",
            )
        else:
            file = SimpleUploadedFile(role + ".tif", path.read_bytes(), "image/tiff")
        upload = store_upload(env["owner"], env["project"].id, file, uuid.uuid4().hex)
        resource = upload.resource
        resource.source, resource.owner_only = "catalog-fixture", False
        resource.save()
        roles[role] = resource.id
        upload.delete()
    response = post(
        env,
        "/api/agent/workflow-uploads/references/",
        {"batchId": env["batch"], "resourceIds": list(roles.values())},
    )
    assert response.status_code == 200, response.content
    assert all(item["source"] == "catalog" for item in response.json()["items"])
    return roles


def conversation_run(env, batch, *, reuse=False):
    conversation = Conversation.objects.create(
        owner=env["owner"], mode="agent", title="离线完整演示"
    )
    response = post(
        env,
        f"/api/agent/conversations/{conversation.id}/runs/",
        {
            "model": "mock",
            "prompt": "检查三要素并比较找矿远景区",
            "reasoningEffort": "medium",
            "thinkingMode": "deep",
            "idempotencyKey": uuid.uuid4().hex,
            "uploadBatchId": batch,
            "reuseConfirmedConfiguration": reuse,
        },
    )
    assert response.status_code == 202, response.content
    run = AgentRun.objects.get(pk=response.json()["id"])
    process(run, env["owner"], env["policy"], lambda: None, lambda *args: None)
    run.refresh_from_db()
    run.status = "succeeded"
    run.save(update_fields=["status"])
    return run


def native_task(task):
    directory = app_path("journey", str(task.id))
    inputs = directory / "inputs"
    inputs.mkdir(parents=True)
    paths = {
        record.key: inputs / Path(freeze_input(record, inputs)["path"]).name
        for record in task.input_records.all()
    }
    context = Context(directory / "outputs", paths, task.parameters)
    if task.version.algorithm.identifier == "input-raster-class-masks":
        from apps.core import data_adapters

        with patch.dict("sys.modules", {"data_adapters": data_adapters}):
            runpy.run_path(
                str(ROOT / "examples/compute/input-adapters/raster_masks.py")
            )["run"](context)
    else:
        suffix = task.version.algorithm.identifier.removeprefix("geology-multi-")
        load(suffix)(context)
    metadata = quality_metadata(
        read_quality_report(context.directory, task.version.manifest)
    )
    for spec in task.version.manifest["outputs"]:
        path = context.output_path(spec["file"])
        if not path.exists() and not spec["required"]:
            continue
        ComputeOutput.objects.create(
            task=task,
            key=spec["key"],
            label=spec["label"],
            kind=spec["kind"],
            file_name=path.name,
            path=path.relative_to(app_path()).as_posix(),
            size_bytes=path.stat().st_size,
            checksum=checksum(path),
            metadata={**inspect_output(path, spec["kind"]), **metadata},
        )
    task.status = "succeeded"
    task.save(update_fields=["status"])
    RuntimeLease.objects.filter(name="worker").update(heartbeat=timezone.now())


def test_system_data_to_clean_results_and_new_conversation_reuse(
    generic, tmp_path, monkeypatch, settings
):
    settings.AGENT_MODELS = [{**model, "qwen": True} for model in settings.AGENT_MODELS]
    generic["project"].code = "02"
    generic["project"].save(update_fields=["code"])
    monkeypatch.setattr("apps.compute.services.candidate", candidate)
    monkeypatch.setattr(
        "apps.agent.provider.model_request",
        lambda *args, **kwargs: pytest.fail("离线流程不得调用模型服务"),
    )
    context, _ = fixture(tmp_path)
    faults = gpd.read_file(context.inputs["faults"])
    left, bottom, _, _ = gpd.read_file(context.inputs["coverage"]).total_bounds
    faults.loc[len(faults)] = {
        "line_id": "F3",
        "geometry": LineString(
            [(left + 125, bottom + 125), (left + 175, bottom + 175)]
        ),
    }
    store(faults.set_crs(32646), context.inputs["faults"])
    register_rules(generic, context)
    register_operators(generic)
    roles = system_references(generic, context)
    run = conversation_run(generic, generic["batch"])
    assert run.research_workflow_id is None
    response = answer(
        generic,
        run,
        answers={f"upload_{identity}": role for role, identity in roles.items()},
    )
    assert response.status_code == 200, response.content
    run.refresh_from_db()
    workflow = run.research_workflow
    assert workflow.plan["uploadInputs"]["faults"] == roles["faults"]
    run_workflow(workflow.id)
    workflow.refresh_from_db()
    assert (
        workflow.status == "waiting_approval"
        and workflow.plan["phase"] == "review_mapping"
    )
    assert answer(generic, run, answer="确认字段含义").status_code == 200
    run_workflow(workflow.id)
    workflow.refresh_from_db()
    assert workflow.plan["phase"] == "review_plan" and not workflow.execute_operators
    assert DataResource.objects.get(
        pk=workflow.plan["inputs"]["faults"]
    ).item_count == len(faults), workflow.plan.get("inputPreparation")
    assert not ComputeTask.objects.exists()
    assert answer(generic, run, answer="都听你的").status_code == 400
    assert answer(generic, run, answer="确认计划").status_code == 200
    approvals = []
    stages = []
    for _ in range(35):
        RuntimeLease.objects.filter(name="worker").update(heartbeat=timezone.now())
        workflow.refresh_from_db()
        if workflow.status == "succeeded":
            break
        assert workflow.status not in {"failed", "cancelled"}, (
            workflow.detail,
            [
                (stage["name"], [item["key"] for item in stage.get("outputs", [])])
                for stage in workflow.plan["stages"]
            ],
        )
        if workflow.status == "waiting_approval":
            phase = workflow.plan["phase"]
            if phase == "review_modifications":
                suggestions = workflow.plan["modificationReview"]["suggestions"]
                approvals = [
                    item["id"]
                    for item in suggestions
                    if item.get("status") == "suggested"
                ]
                assert approvals
                payload = {
                    "planHash": workflow.plan_hash,
                    "selectedSuggestionIds": approvals,
                }
            else:
                assert phase == "review_results"
                payload = {"planHash": workflow.plan_hash}
            response = post(
                generic, f"/api/agent/workflows/{workflow.id}/confirm/", payload
            )
            assert response.status_code == 200, response.content
        elif workflow.status == "waiting_compute":
            stage = workflow.plan["stages"][workflow.plan["stageIndex"]]
            task = ComputeTask.objects.get(pk=stage["taskId"])
            if task.status == "queued":
                stages.append(stage["name"])
                native_task(task)
            resume_waiting()
            for record in ComputeImport.objects.filter(status="queued"):
                process_import(record)
                record.refresh_from_db()
                assert record.status == "ready", record.error
            resume_waiting()
        else:
            run_workflow(workflow.id)
    workflow.refresh_from_db()
    assert workflow.status == "succeeded", workflow.detail
    assert stages == ["check", "apply", "recheck", "relations", "prospect"]
    assert workflow.plan["modificationReview"]["approvedSuggestionIds"] == approvals
    apply = next(stage for stage in workflow.plan["stages"] if stage["name"] == "apply")
    outputs = {
        output.key: output
        for output in ComputeTask.objects.get(pk=apply["taskId"]).outputs.all()
    }
    original = gpd.read_file(context.inputs["lithology"])
    corrected = gpd.read_file(app_path(outputs["lithology"].path))
    assert len(corrected) < len(original)
    for key in ("lithology", "final_faults", "final_alterations"):
        if key not in outputs:
            assert key == "final_alterations"
            if "alterations" in outputs:
                state = gpd.read_file(app_path(outputs["alterations"].path))
                assert len(state) > 0 and set(state["state"]) == {"exclude"}
            else:
                excluded_pixels = 0
                minerals = (
                    ("alteration_stack",)
                    if "alteration_stack_corrected" in outputs
                    else (
                        "hematite",
                        "chlorite",
                        "hydromica",
                        "calcite",
                        "dolomite",
                    )
                )
                for mineral in minerals:
                    with (
                        rasterio.open(
                            app_path(outputs[mineral + "_corrected"].path)
                        ) as corrected_raster,
                        rasterio.open(
                            app_path(outputs[mineral + "_weight"].path)
                        ) as weight_raster,
                    ):
                        assert corrected_raster.count == weight_raster.count >= 1
                        assert corrected_raster.crs == weight_raster.crs
                        assert corrected_raster.crs is not None
                        assert corrected_raster.shape == weight_raster.shape
                        assert corrected_raster.transform == weight_raster.transform
                        weights = weight_raster.read(masked=True)
                        assert (weights >= 0).all() and (weights <= 1).all()
                        excluded_pixels += int((weights == 0).sum())
                assert excluded_pixels > 0
            continue
        frame = gpd.read_file(app_path(outputs[key].path))
        assert not {
            "action",
            "state",
            "weight",
            "excluded",
            "rule_id",
            "snapshot_hash",
        } & set(frame.columns)
        assert frame.geometry.is_valid.all()
    changes = read(app_path(outputs["changes"].path))
    assert changes and all(row["issue_id"] for row in changes)
    assert any(
        row["element"] == "structure" and row["action"] == "exclude" for row in changes
    ), [(row["feature_id"], row["element"], row["action"]) for row in changes]
    assert any(
        row["element"] == "alteration" and row["action"] == "exclude" for row in changes
    )
    clean_faults = gpd.read_file(app_path(outputs["final_faults"].path))
    assert len(clean_faults) < len(faults)
    removed_faults = {
        row["feature_id"]
        for row in changes
        if row["element"] == "structure" and row["action"] == "exclude"
    }
    assert not removed_faults & set(clean_faults["line_id"])
    if "final_alterations" in outputs:
        clean_alterations = gpd.read_file(app_path(outputs["final_alterations"].path))
        removed_alterations = {
            row["feature_id"]
            for row in changes
            if row["element"] == "alteration" and row["action"] == "exclude"
        }
        assert not removed_alterations & set(clean_alterations["feature_id"])
    assert outputs["changes_lithology_issues"].kind == "vector"
    report = post(generic, f"/api/agent/workflows/{workflow.id}/report/", {})
    assert report.status_code in {200, 201}, report.content
    prospect = next(
        stage for stage in workflow.plan["stages"] if stage["name"] == "prospect"
    )
    prospect_task = ComputeTask.objects.get(pk=prospect["taskId"])
    zones = prospect_task.outputs.filter(key="after_zones").first()
    if zones is not None:
        frame = gpd.read_file(app_path(zones.path))
        assert "grade" not in frame.columns and frame.geometry.is_valid.all()
        assert set(frame.geom_type) <= {"Polygon", "MultiPolygon"}
        assert set(frame.columns) == {
            "zone_id",
            "priority_rank",
            "area_km2",
            "explanation",
            "evidence_json",
            "geometry",
        }
        assert frame.geometry.area.sum() == pytest.approx(
            frame.geometry.union_all().area, rel=1e-6
        )
    else:
        statistics = read(app_path(prospect_task.outputs.get(key="statistics").path))
        assert statistics and all(int(row["zone_count"]) == 0 for row in statistics)
        assert all(float(row["area_km2"]) == 0 for row in statistics)
        evidence = read(app_path(prospect_task.outputs.get(key="evidence").path))
        assert all(row["phase"] != "after" for row in evidence)
    saved = LogicConfiguration.objects.get(
        owner=generic["owner"], project_tag=generic["project"]
    )
    assert set(saved.value["resourceIds"]) == set(roles.values())
    assert saved.value["reasoningEffort"] == "medium"
    assert saved.value["prompt"] == workflow.goal
    batch = uuid.uuid4().hex
    response = post(generic, "/api/agent/logic-configuration/", {"batchId": batch})
    assert response.status_code == 200, response.content
    assert response.json()["configuration"]["prompt"] == saved.value["prompt"]
    assert response.json()["configuration"]["reasoningEffort"] == "medium"
    monkeypatch.setattr(
        "apps.agent.workflow_roles.recognize_roles",
        lambda *args: pytest.fail("角色不应重复识别"),
    )
    monkeypatch.setattr(
        "apps.agent.generic_mapping.model_targets",
        lambda *args: pytest.fail("字段不应重复识别"),
    )
    fresh = conversation_run(generic, batch, reuse=True)
    assert fresh.research_workflow_id != workflow.id
    run_workflow(fresh.research_workflow_id)
    restored = AgentWorkflow.objects.get(pk=fresh.research_workflow_id)
    assert restored.plan["reusedConfiguration"] is True
    assert restored.plan["confirmedMapping"] == saved.value["fieldMapping"]
    assert (
        restored.status == "waiting_approval"
        and restored.plan["phase"] == "review_plan"
    )
    assert not restored.execute_operators and not restored.plan.get(
        "modificationReview"
    )
    detail = generic["client"].get(
        f"/api/agent/conversations/{run.conversation_id}/",
        HTTP_X_PROJECT_ID=str(generic["project"].id),
    )
    assert detail.status_code == 200 and detail.json()["runs"][0]["researchIntent"][
        "workflowId"
    ] == str(workflow.id)
    assert DataResource.objects.filter(
        pk__in=roles.values(), status="active"
    ).count() == len(roles)
