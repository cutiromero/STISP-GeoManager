"""The task agent binds actual spectral bands, repairs a bad index, and computes."""

import hashlib
import json
from pathlib import Path
import runpy
from uuid import uuid4

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from apps.agent import provider
from apps.business_flows import catalog, engine, runtime
from apps.business_flows.builtins import source_summary_definition
from apps.business_flows.node_contracts import TOOLS
from apps.compute.data import freeze_input, inspect_output
from apps.compute.models import (
    AlgorithmResource,
    AlgorithmVersion,
    ComputeOutput,
    ComputeTask,
)
from apps.compute.packages import checksum, validate_manifest
from apps.core.storage import app_path
from apps.projects.context import project_scope
from apps.raster.services.importer import import_raster_file
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_business_flow_operator_runtime import operators  # noqa: F401
from tests.integration.test_business_flow_main_agent import install_model
from tests.unit.test_geology_multi_algorithms import Context

# ruff: noqa: F811
ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.efficiency


def test_main_agent_selects_real_bands_and_repairs_before_compute(
    operators, monkeypatch, tmp_path
):
    env = operators
    calls = install_model(monkeypatch)
    fallback = provider.stream
    source = tmp_path / "six_bands.tif"
    labels = ["Blue", "Green", "Red", "Red edge", "NIR", "SWIR"]
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=6,
        dtype="float32",
        crs="EPSG:32646",
        transform=from_origin(300000, 4000000, 10, 10),
    ) as stream:
        for index, name in enumerate(labels, 1):
            stream.write(
                np.full(
                    (2, 2),
                    2 if name == "Red" else 6 if name == "NIR" else 9,
                    dtype="float32",
                ),
                index,
            )
            stream.set_band_description(index, name)
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    with project_scope(env["scope"]):
        dataset = import_raster_file(
            source,
            name="六波段合成验证影像",
            uploader_id=env["owner"].pk,
            owner_only=True,
        )
        manifest = validate_manifest(
            json.loads(
                (ROOT / "examples/compute/raster-ndvi/operator.yaml").read_text()
            )
        )
        algorithm = AlgorithmResource.objects.create(
            identifier="raster-ndvi", name="实际波段NDVI", created_by=env["owner"]
        )
        version = AlgorithmVersion.objects.create(
            algorithm=algorithm,
            version=manifest["version"],
            status="published",
            manifest=manifest,
            checksum="e" * 64,
            runtime_digest="sha256:" + "a" * 64,
        )
        definition = source_summary_definition(main_agent=True)
        definition["inputRequirements"][0]["dataTypes"] = ["raster"]
        definition["nodes"][0].update(
            id="calculate",
            title="计算实际NDVI",
            dataRoles=["source"],
            contract={
                "goal": "根据真实波段语义计算NDVI",
                "acceptance": ["根据实际波段语义计算并读取真实输出"],
                "requiredOutputs": [
                    {"name": "result", "semanticType": "operator_result"}
                ],
                "tools": sorted(TOOLS),
                "maxSteps": 12,
                "maxModelCalls": 12,
            },
        )
        definition["nodes"][1]["dependsOn"] = ["calculate"]
        _, flow_version = catalog.register_flow(
            env["admin"],
            {
                "code": "ndvi-main-" + uuid4().hex[:8],
                "name": "主执行波段适配验证",
                "definition": definition,
            },
        )
        workflow = runtime.start_flow(
            env["owner"],
            flow_version,
            {
                "model": "mock",
                "goal": "选择影像的真实红光和近红外波段，得到NDVI",
                "inputs": {"source": dataset.data_resource_id},
                "idempotencyKey": uuid4().hex,
            },
        )

    def respond(model, messages, maximum, guard, **options):
        packet = json.loads(messages[1]["content"])
        context = packet.get("nodeContext", {})
        if (
            context.get("task", {}).get("phase") != "work"
            or packet["node"]["id"] != "calculate"
        ):
            yield from fallback(model, messages, maximum, guard, **options)
            return
        guard()
        calls.append({"packet": packet, "messages": messages})
        history = context["history"]
        bands = next(
            row["result"]["bandMetadata"]
            for row in packet["evidence"]
            if row["id"] == f"resource-{dataset.data_resource_id}"
        )
        selected = {
            "red": next(row["band"] for row in bands if row["description"] == "Red"),
            "nir": next(row["band"] for row in bands if row["description"] == "NIR"),
        }
        args = {
            "versionId": version.pk,
            "inputs": {"image": dataset.data_resource_id},
            "parameters": selected,
            "fieldMappings": {},
        }
        if not any(row["action"] == "operator_catalog" for row in history):
            result = {
                "action": "operator_catalog",
                "arguments": {"keyword": "raster-ndvi"},
            }
        elif not any(row["action"] == "preflight_operator" for row in history):
            result = {
                "action": "preflight_operator",
                "arguments": {**args, "parameters": {**selected, "red": 99}},
            }
        elif not context.get("observation", {}).get("result", {}).get(
            "valid"
        ) and not any(row["action"] == "run_operator" for row in history):
            result = {"action": "preflight_operator", "arguments": args}
        elif not any(row["action"] == "run_operator" for row in history):
            result = {
                "action": "run_operator",
                "arguments": {**args, "remedy": "adjust_parameters"},
            }
        else:
            refs = [row["id"] for row in packet["evidence"] if row["kind"] == "output"]
            result = {
                "action": "finish_node",
                "arguments": {
                    "summary": "已按真实红光与近红外通道完成NDVI计算",
                    "outputs": [
                        {
                            "name": "result",
                            "semanticType": "operator_result",
                            "evidenceId": refs[0],
                        }
                    ],
                    "evidenceIds": refs,
                    "limitations": [],
                    "acceptanceChecks": context["contract"]["acceptance"],
                },
            }
        yield json.dumps(result, ensure_ascii=False)

    monkeypatch.setattr(provider, "stream", respond)
    produced = None
    with project_scope(env["scope"]):
        for _ in range(35):
            engine.advance(workflow.pk)
            workflow.refresh_from_db()
            for task in ComputeTask.objects.filter(
                owner=env["owner"], status="queued", version=version
            ):
                assert task.parameters == {"red": 3, "nir": 5}
                directory = app_path("main-ndvi-test", str(task.pk))
                inputs = directory / "inputs"
                inputs.mkdir(parents=True)
                paths = {
                    row.key: inputs / Path(freeze_input(row, inputs)["path"]).name
                    for row in task.input_records.all()
                }
                context = Context(directory / "outputs", paths, task.parameters)
                runpy.run_path(str(ROOT / "examples/compute/raster-ndvi/main.py"))[
                    "run"
                ](context)
                produced = context.output_path("ndvi.tif")
                ComputeOutput.objects.create(
                    task=task,
                    key="ndvi",
                    label="实际NDVI",
                    kind="raster",
                    file_name="ndvi.tif",
                    path=produced.relative_to(app_path()).as_posix(),
                    size_bytes=produced.stat().st_size,
                    checksum=checksum(produced),
                    metadata=inspect_output(produced, "raster"),
                )
                task.status = "succeeded"
                task.save(update_fields=["status"])
            if workflow.status in {"succeeded", "failed", "waiting_approval"}:
                break
        assert workflow.status == "succeeded", workflow.detail
        assert produced is not None
        with rasterio.open(produced) as output:
            np.testing.assert_allclose(output.read(1), 0.5)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original
    assert any(row["packet"].get("nodeContext", {}).get("failure") for row in calls)
