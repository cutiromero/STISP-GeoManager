"""Historical glacier inputs come from observed and authorized task lineage."""

from copy import deepcopy
from datetime import date
from hashlib import sha256
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.agent.compute_tools import authorized_task
from apps.agent.models import AgentWorkflow
from apps.business_flows import glacier_history
from apps.business_flows.state import state
from apps.catalog.models import DataResource, ResourceObservationMetadata
from apps.compute.models import (
    AlgorithmResource,
    AlgorithmVersion,
    ComputeImport,
    ComputeInput,
    ComputeOutput,
    ComputeTask,
)
from apps.compute.packages import ComputeError
from apps.projects.context import ProjectScope, project_scope
from apps.raster.models import RasterDataset
from tests.integration.test_compute import setup_compute

__all__ = ["setup_compute"]

pytestmark = pytest.mark.efficiency
POLICY = {"dataTypes": ["raster"]}
GRID = {
    "coordinateSystem": "EPSG:32643",
    "size": [30, 30],
    "geoTransform": [500000, 3, 0, 4000000, 0, -3],
}
INTERPRET = {
    "id": "interpret",
    "review": {"ai": False, "human": False},
    "kind": "operator",
}
COMPARE = {
    "id": "compare",
    "review": {"ai": False, "human": False},
    "kind": "operator",
    "dependsOn": ["interpret"],
    "inputBindings": {
        "current": {"nodeId": "interpret", "outputKey": "classification"}
    },
}


def version(user, identifier, number):
    algorithm, _ = AlgorithmResource.objects.get_or_create(
        identifier=identifier, defaults={"created_by": user, "name": identifier}
    )
    return AlgorithmVersion.objects.create(
        algorithm=algorithm, version=number, status="published"
    )


def scene(user, infer, day, *, series="t43-4-1", shift=False, trial=False):
    token = uuid4().hex
    source = DataResource.objects.create(
        name="测试原始影像",
        code="raw-" + token,
        data_type="raster",
        file_format="GeoTIFF",
        storage_path=token + ".tif",
        status="active",
        maintainer=user,
    )
    if day:
        ResourceObservationMetadata.objects.create(
            resource=source,
            family="raster",
            collection_key=series,
            starts_at=day,
            ends_at=day,
            precision="day",
        )
    task = ComputeTask.objects.create(
        owner=user,
        version=infer,
        name=token,
        idempotency_key=token,
        status="succeeded",
        trial=trial,
        finished_at=timezone.now(),
    )
    grid = deepcopy(GRID)
    if shift:
        grid["geoTransform"][0] += 3
    ComputeInput.objects.create(
        task=task,
        key="image",
        resource=source,
        checksum=sha256(token.encode()).hexdigest(),
        snapshot={"updatedAt": source.updated_at.isoformat(), "rasterMetadata": grid},
    )
    result = DataResource.objects.create(
        name="测试分类",
        code="result-" + token,
        data_type="raster",
        file_format="GeoTIFF",
        storage_path="result-" + token + ".tif",
        status="active",
        is_compute_result=True,
        maintainer=user,
    )
    output = ComputeOutput.objects.create(
        task=task,
        key="classification",
        kind="raster",
        file_name="classification.tif",
        path=token + ".tif",
        size_bytes=1,
        checksum=sha256((token + "classification").encode()).hexdigest(),
        metadata={
            "qualityCheck": {
                "version": 1,
                "status": "passed",
                "summary": "fixed",
                "metrics": {},
            }
        },
    )
    RasterDataset.objects.create(
        data_resource=result,
        name=result.name,
        code=result.code,
        source_relative_path=result.storage_path,
        status="ready",
        raster_kind="categorical",
        source_checksum_sha256=output.checksum,
    )
    ComputeImport.objects.create(
        output=output, resource=result, requested_by=user, status="ready"
    )
    return source, result, task


def workflow(user, task, comparison):
    node = {**COMPARE, "algorithmVersionId": comparison.pk}
    work = AgentWorkflow.objects.create(
        owner=user,
        workflow_type="business_flow",
        goal="冰川样例",
        model="test",
        status="succeeded",
        idempotency_key="glacier-auto",
        parameters={
            "_businessFlow": {"definitionSnapshot": {"nodes": [INTERPRET, node]}}
        },
    )
    state(work)["nodes"]["interpret"].update(
        status="succeeded", computeTaskId=str(task.pk)
    )
    work.save(update_fields=["plan"])
    return work, node


def test_latest_registered_matching_classification_and_revocation(setup_compute):
    e = setup_compute
    user, admin, project = e["owner"], e["admin"], e["project"]
    with project_scope(ProjectScope((project.pk,), project.pk, user.pk)):
        infer = version(user, glacier_history.INFERENCE, "1.0.0")
        compare = version(
            user, glacier_history.COMPARISON, glacier_history.AUTOMATIC_VERSION
        )
        curr_source, current, task = scene(user, infer, date(2025, 9, 20))
        work, node = workflow(user, task, compare)
        _, older, _ = scene(admin, infer, date(2022, 9, 20))
        prev_source, previous, _ = scene(admin, infer, date(2023, 9, 20))
        scene(admin, infer, date(2024, 9, 21), trial=True)
        scene(admin, infer, date(2024, 9, 22), shift=True)
        scene(admin, infer, date(2024, 9, 23), series="other-site")
        scene(admin, infer, date(2025, 9, 21))
        scene(admin, infer, None)
        another_version = version(user, glacier_history.INFERENCE, "2.0.0")
        scene(admin, another_version, date(2024, 9, 24))

        result, evidence = glacier_history.resolve(work, user, POLICY, node, current.pk)
        assert result.pk == previous.pk
        assert evidence == {
            "currentSourceId": curr_source.pk,
            "currentDate": "2025-09-20",
            "baselineSourceId": prev_source.pk,
            "baselineResourceId": previous.pk,
            "baselineDate": "2023-09-20",
            "reason": "matched",
        }

        comparison_task = ComputeTask.objects.create(
            owner=user,
            version=compare,
            name="自动双期",
            idempotency_key="automatic",
            status="succeeded",
        )
        work.steps.create(
            sequence=1, kind="compare", compute_task_id=comparison_task.pk
        )
        ComputeInput.objects.create(
            task=comparison_task, key="baseline", resource=previous
        )
        assert (
            authorized_task(user, comparison_task.pk, POLICY, workflow=work).pk
            == comparison_task.pk
        )
        previous.owner_only = True
        previous.save(update_fields=["owner_only"])
        with pytest.raises(PermissionDenied):
            authorized_task(user, comparison_task.pk, POLICY, workflow=work)
        result, _ = glacier_history.resolve(work, user, POLICY, node, current.pk)
        assert result.pk == older.pk
        with pytest.raises(ComputeError, match="本期分类不是"):
            glacier_history.resolve(work, user, POLICY, node, older.pk)

        # A later metadata edit is not evidence of what was classified before it.
        curr_source.updated_at = timezone.now()
        curr_source.save(update_fields=["updated_at"])
        result, evidence = glacier_history.resolve(work, user, POLICY, node, current.pk)
        assert result is None
        assert evidence == {
            "currentSourceId": curr_source.pk,
            "reason": "no_current_date",
        }


def test_preflight_uses_real_raster_binding_without_model_history_inputs(
    setup_compute, settings, monkeypatch
):
    import json

    import numpy as np
    import rasterio
    from rasterio.transform import Affine

    from apps.agent import policy as policy_module
    from apps.business_flows.definitions import normalize_definition
    from apps.business_flows.node_loop import execute_tool, loop_state
    from apps.compute.packages import PreflightRequired, validate_manifest
    from apps.core.storage import raster_source_path

    env = setup_compute
    user, project = env["owner"], env["project"]
    policy = {**POLICY, "operatorEnabled": True}
    monkeypatch.setattr(policy_module, "require_access", lambda *args: policy)

    with project_scope(ProjectScope((project.pk,), project.pk, user.pk)):
        infer = version(user, glacier_history.INFERENCE, "1.0.0")
        compare = version(
            user, glacier_history.COMPARISON, glacier_history.AUTOMATIC_VERSION
        )
        compare.manifest = validate_manifest(
            json.loads(
                (
                    settings.PROGRAM_ROOT
                    / "examples/compute/glacier-temporal-compare/operator.yaml"
                ).read_text()
            )
        )
        compare.save(update_fields=["manifest"])
        raw, current, task = scene(user, infer, date(2025, 9, 20))
        RasterDataset.objects.create(
            data_resource=raw,
            name=raw.name,
            code=raw.code,
            source_relative_path=raw.storage_path,
            status="ready",
        )
        _, previous, _ = scene(env["admin"], infer, date(2024, 9, 20))
        for resource in (current, previous):
            path = raster_source_path(resource.storage_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(
                path,
                "w",
                driver="GTiff",
                width=30,
                height=30,
                count=1,
                dtype="uint8",
                nodata=255,
                crs=GRID["coordinateSystem"],
                transform=Affine.from_gdal(*GRID["geoTransform"]),
            ) as target:
                target.write(np.full((30, 30), 1, dtype=np.uint8), 1)
        spec = json.loads(
            (
                settings.PROGRAM_ROOT
                / "examples/business-flows/glacier-monitoring-dynamic.json"
            ).read_text()
        )
        spec["nodes"][0]["algorithmVersionId"] = infer.pk
        spec["nodes"][1]["algorithmVersionId"] = compare.pk
        spec = normalize_definition(spec, authored=True)
        node = spec["nodes"][1]
        run = AgentWorkflow.objects.create(
            owner=user,
            model="test",
            workflow_type="business_flow",
            goal="自动检索",
            plan={"inputs": {"image": raw.pk}},
            resource_ids=[raw.pk],
            idempotency_key="auto-real-preflight",
            parameters={
                "_businessFlow": {
                    "name": "冰川比较",
                    "definitionSnapshot": spec,
                    "executorSession": {"active": True},
                }
            },
        )
        output_id = task.outputs.get(key="classification").pk
        state(run)["nodes"]["interpret"].update(
            status="succeeded",
            computeTaskId=str(task.pk),
            contractOutputs=[
                {"name": "classification", "evidenceId": f"output-{output_id}"}
            ],
        )
        run.steps.create(sequence=1, kind="interpret", compute_task_id=task.pk)
        run.save(update_fields=["plan"])
        item = state(run)["nodes"]["compare"]

        def call(action, arguments):
            return execute_tool(
                run,
                user,
                policy,
                node,
                item,
                action,
                arguments,
                [],
                node["contract"],
                lambda: None,
            )

        with pytest.raises(ComputeError, match="不能手工指定"):
            call("preflight_operator", {"inputs": {"baseline": previous.pk}})
        with pytest.raises(ComputeError, match="不能手工指定"):
            call("preflight_operator", {"parameters": {"baseline_date": "2024-01-01"}})
        planned = call("preflight_operator", {})
        assert (
            planned["valid"]
            and planned["glacierHistory"]["baselineResourceId"] == previous.pk
        )
        loop = loop_state(item)
        assert loop["validatedLaunch"]["inputs"] == {"current": current.pk}
        assert loop["validatedLaunch"]["parameters"] == {}

        # A permission change invalidates the paired preflight, not just a display label.
        previous.owner_only = True
        previous.save(update_fields=["owner_only"])
        with pytest.raises(PreflightRequired):
            call("run_operator", {"usePreflight": True})
        fallback = call("preflight_operator", {})
        assert fallback["glacierHistory"]["reason"] == "no_prior"
