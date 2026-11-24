from datetime import date, datetime, timezone
from io import BytesIO
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.transform import from_bounds

from apps.agent.models import AgentWorkflow
from apps.business_flows.models import BusinessFlowDefinition
from apps.business_flows.state import state
from apps.catalog.models import DataResource
from apps.compute.models import (
    AlgorithmResource,
    AlgorithmVersion,
    ComputeImport,
    ComputeInput,
    ComputeOutput,
    ComputeTask,
)
from apps.ecology.glacier import (
    MANANS_FLOW_CODE,
    MANANS_OPERATOR,
    MANANS_STANDARD_TASK,
    MANANS_VARIANT,
    TASK_KEY,
    publish_manans,
    publish_workflow,
    resolve_registered,
    resolve_manans_registered,
)
from apps.ecology.models import RemoteSensingProduct
from apps.ecology.monitoring import register_product
from apps.ecology.official_monitoring import official_snapshot
from apps.projects.context import ProjectScope, project_scope
from apps.projects.features import set_feature
from apps.raster.models import RasterDataset
from apps.raster.services import renderer
from apps.raster.services.geo_utils import tile_bounds_3857
from tests.integration.test_ecology_monitoring import setup_monitor

__all__ = ["setup_monitor"]

pytestmark = pytest.mark.efficiency
QUALITY = {"status": "passed", "version": 1, "summary": "分类通过", "metrics": {}}


def test_registered_previous_intersection_and_only_publish_classification(
    setup_monitor, monkeypatch, tmp_path
):
    admin, reader, project, _, feature, _, raw, base = setup_monitor
    set_feature(
        admin,
        feature,
        project=project,
        enabled=True,
        config={
            "source": "remote_sensing_products",
            "scenes": ["glacier"],
            "title": "冰川",
            "initialView": {"center": [72, 38], "zoom": 3, "regionZoom": 10},
        },
    )

    def raster(code, extent, *, result=False):
        resource = DataResource.objects.create(
            name=code,
            code=code,
            maintainer=admin,
            data_type="raster",
            storage_path=code + ".tif",
            coordinate_system="EPSG:32643",
            is_compute_result=result,
        )
        RasterDataset.objects.create(
            data_resource=resource,
            status="ready",
            raster_kind="categorical",
            code=code,
            bounds_4326=extent,
            source_relative_path=resource.storage_path,
        )
        return resource

    def historical(code, extent, when, region):
        result = raster(code, extent)
        product, _ = register_product(
            admin,
            {
                **base,
                "code": code,
                "name": code,
                "scene": "glacier",
                "resourceId": result.pk,
                "registrationDate": when,
                "sourceResourceIds": [raw.pk],
                "referenceRole": "standard",
                "statistics": {"valid_pixels": 100},
            },
        )
        product.metadata.update(glacierTask=TASK_KEY, glacierRegion=region)
        product.save(update_fields=["metadata"])
        return product

    def compute(identifier, version):
        algo = AlgorithmResource.objects.create(
            identifier=identifier, name=identifier, created_by=admin
        )
        av = AlgorithmVersion.objects.create(algorithm=algo, version=version)
        return ComputeTask.objects.create(
            owner=admin,
            name=identifier,
            status="succeeded",
            version=av,
            idempotency_key=identifier,
        )

    with project_scope(ProjectScope((project.pk,), project.pk, admin.pk)):
        RasterDataset.objects.create(
            data_resource=raw,
            status="ready",
            bounds_4326=[71, 38, 73, 40],
            code="source",
        )
        previous = historical("prior", [72, 39, 74, 41], "2026-11-22", "station")
        historical("same-day", [72, 39, 74, 41], "2026-11-23", "station")
        historical("outside", [80, 30, 81, 31], "2026-11-22", "outside")
        test_workflow = SimpleNamespace(
            created_at=datetime(2026, 11, 23, tzinfo=timezone.utc)
        )
        baseline, receipt = resolve_registered(
            test_workflow, admin, SimpleNamespace(resource_id=raw.pk)
        )
        assert baseline.pk == previous.data_resource_id
        assert receipt["baselineDate"] == "2026-11-22"
        assert receipt["baselineBasis"] == "registered_codes"
        assert previous.acquired_on is None

        classification = raster("current", [71, 38, 73, 40], result=True)
        tile = (3, 5, 3)
        bounds = tile_bounds_3857(*tile)
        raster_path = tmp_path / "current.tif"
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=4,
            height=1,
            count=1,
            dtype="uint8",
            crs="EPSG:3857",
            transform=from_bounds(*bounds, 4, 1),
            nodata=255,
        ) as dst:
            dst.write(np.array([[0, 1, 2, 255]], dtype=np.uint8), 1)
        colors = [
            {"value": 0, "color": "#00000000", "label": "背景"},
            {"value": 1, "color": "#4bade8", "label": "洁净冰川"},
            {"value": 2, "color": "#eab764", "label": "表碛冰川"},
            {"value": 255, "color": "#00000000", "label": "缺测"},
        ]
        dataset = RasterDataset.objects.get(data_resource=classification)
        dataset.bounds_3857 = list(bounds)
        dataset.default_rules = {"mode": "unique", "uniqueValues": colors}
        dataset.processed_gdalinfo = {"geoManager": {"dynamicTiles": True}}
        dataset.save(
            update_fields=["bounds_3857", "default_rules", "processed_gdalinfo"]
        )
        monkeypatch.setattr(renderer, "raster_processed_path", lambda _: raster_path)
        infer = compute("glacier-b15-infer", "1.1.0")
        output = ComputeOutput.objects.create(
            task=infer,
            key="classification",
            kind="raster",
            file_name="classification.tif",
            size_bytes=99,
            path="tif",
            checksum="b" * 64,
            metadata={
                "qualityCheck": {
                    **QUALITY,
                    "metrics": {"classCounts": {"0": 80, "1": 10, "2": 10, "255": 0}},
                },
                "knowledgeFacts": {
                    "checkpointSha256": "c" * 64,
                    "coverageBasis": "image_extent",
                },
            },
        )
        ComputeInput.objects.create(task=infer, key="image", resource=raw)
        compare = compute("glacier-temporal-compare", "1.3.0")
        compare.parameters.update(
            region="station",
            baseline_product_id=previous.pk,
            baseline_date="2026-11-22",
            baseline_basis="registered_codes",
        )
        compare.save(update_fields=["parameters"])
        ComputeInput.objects.create(
            task=compare, key="current", resource=classification
        )
        ComputeInput.objects.create(task=compare, key="baseline", resource=baseline)
        ComputeOutput.objects.create(
            task=compare,
            key="coverage",
            kind="table",
            file_name="coverage.csv",
            path="csv",
            size_bytes=99,
            checksum="a" * 64,
            metadata={
                "qualityCheck": {
                    **QUALITY,
                    "metrics": {
                        "comparisonStatus": "compared",
                        "commonAreaKm2": 0.0009,
                        "changedPercent": 20,
                        "netClass1Km2": 0.00009,
                        "netClass2Km2": -0.00009,
                        "netIceAreaKm2": None,
                    },
                }
            },
        )
        flow = BusinessFlowDefinition.objects.create(
            code="glacier-monitoring-dynamic", name="冰川", owner=admin
        )
        workflow = AgentWorkflow.objects.create(
            owner=admin,
            workflow_type="business_flow",
            status="succeeded",
            idempotency_key="glacier-board",
            parameters={
                "_businessFlow": {
                    "flowId": flow.pk,
                    "definitionSnapshot": {"nodes": []},
                },
            },
            plan={
                "businessFlow": {
                    "nodes": {
                        "interpret": {
                            "status": "succeeded",
                            "computeTaskId": str(infer.pk),
                            "contractOutputs": [
                                {
                                    "name": "classification",
                                    "evidenceId": f"output-{output.pk}",
                                }
                            ],
                        },
                        "compare": {
                            "status": "succeeded",
                            "computeTaskId": str(compare.pk),
                        },
                    }
                }
            },
        )
        AgentWorkflow.objects.filter(pk=workflow.pk).update(
            created_at=test_workflow.created_at
        )
        ComputeImport.objects.create(
            output=output,
            status="ready",
            resource=classification,
            requested_by=admin,
            request_source=f"workflow:{workflow.pk}",
        )
        product = publish_workflow(workflow.pk, admin.pk)
        assert publish_workflow(workflow.pk, admin.pk).pk == product.pk
        assert product.data_resource_id == classification.pk
        assert product.acquired_on is None
        assert product.metadata["monitoring"]["registrationDate"] == "2026-11-23"
        assert product.metadata["glacierChange"]["baselineProductId"] == previous.pk
        assert (
            RemoteSensingProduct.objects.filter(
                metadata__monitoring__kind="model"
            ).count()
            == 1
        )
    with project_scope(ProjectScope((project.pk,), project.pk, reader.pk)):
        chosen = next(
            item
            for item in official_snapshot(reader, "glacier")["items"]
            if item["id"] == product.pk
        )
        assert chosen["glacierChange"]["changedPercent"] == 20
        assert not chosen["observedStart"]
        assert chosen["display"]["rules"]["uniqueValues"][0]["color"] == "#364a5c"
        assert (
            RasterDataset.objects.get(pk=dataset.pk).default_rules["uniqueValues"]
            == colors
        )
        rendered = renderer.render_xyz_tile(
            dataset.pk, chosen["display"]["styleHash"], *tile
        )
        with Image.open(BytesIO(rendered)) as png:
            assert png.getpixel((32, 128)) == (54, 74, 92, 255)
            assert png.getpixel((96, 128)) == (75, 173, 232, 255)
            assert png.getpixel((160, 128)) == (234, 183, 100, 255)
            assert png.getpixel((224, 128))[3] == 0
        baseline.owner_only = True
        baseline.save(update_fields=["owner_only"])
        chosen = next(
            item
            for item in official_snapshot(reader, "glacier")["items"]
            if item["id"] == product.pk
        )
        assert chosen["glacierChange"] is None


@pytest.mark.parametrize("with_history", [False, True])
def test_manans_binary_map_retains_acquisition_date_and_original_display(
    setup_monitor, monkeypatch, tmp_path, with_history
):
    admin, reader, project, _, feature, _, raw, base = setup_monitor
    set_feature(
        admin,
        feature,
        project=project,
        enabled=True,
        config={
            "source": "remote_sensing_products",
            "scenes": ["glacier"],
            "title": "冰川",
            "initialView": {"center": [87, 43], "zoom": 3, "regionZoom": 10},
        },
    )
    path = tmp_path / "display.tif"
    path.touch()
    monkeypatch.setattr(renderer, "raster_processed_path", lambda _: path)
    with project_scope(ProjectScope((project.pk,), project.pk, admin.pk)):
        raw.name = "玛纳斯原始影像 · T45TUJ"
        raw.data_date = date(2021, 9, 8)
        raw.save(update_fields=["name", "data_date"])
        bounds = [86, 42, 87, 43]
        metadata = {"size": [10, 10], "geoTransform": [300000, 10, 0, 4800000, 0, -10]}
        RasterDataset.objects.create(
            data_resource=raw,
            status="ready",
            code="manans-raw",
            source_relative_path="manans-raw.tif",
            bounds_4326=bounds,
            source_gdalinfo=metadata,
            source_checksum_sha256="c" * 64,
        )
        result = DataResource.objects.create(
            name="玛纳斯冰川结果",
            code="manans-result",
            data_type="raster",
            storage_path="result.tif",
            coordinate_system="EPSG:32645",
            maintainer=admin,
            is_compute_result=True,
        )
        RasterDataset.objects.create(
            data_resource=result,
            status="ready",
            code="manans-out",
            source_relative_path="manans-out.tif",
            raster_kind="categorical",
            processed_gdalinfo={"geoManager": {"dynamicTiles": True}},
        )
        algo = AlgorithmResource.objects.create(
            identifier=MANANS_OPERATOR,
            name="玛纳斯",
            created_by=admin,
        )
        version = AlgorithmVersion.objects.create(algorithm=algo, version="1.0.0")
        task = ComputeTask.objects.create(
            owner=admin,
            name="玛纳斯",
            status="succeeded",
            version=version,
            idempotency_key="manans-compute",
        )
        ComputeInput.objects.create(
            task=task,
            key="image",
            resource=raw,
            snapshot={"updatedAt": raw.updated_at.isoformat()},
        )
        output = ComputeOutput.objects.create(
            task=task,
            key="classification",
            kind="raster",
            file_name="classification.tif",
            path="classification.tif",
            size_bytes=99,
            checksum="a" * 64,
            metadata={
                "qualityCheck": {
                    **QUALITY,
                    "metrics": {
                        "scene_pixels": 100,
                        "valid_pixels": 80,
                        "glacier_pixels": 20,
                    },
                },
                "knowledgeFacts": {"checkpointSha256": "b" * 64},
            },
        )
        flow = BusinessFlowDefinition.objects.create(
            code=MANANS_FLOW_CODE, name="玛纳斯", owner=admin
        )
        workflow = AgentWorkflow.objects.create(
            owner=admin,
            workflow_type="business_flow",
            status="succeeded",
            idempotency_key="manans-flow",
            parameters={
                "_businessFlow": {
                    "flowId": flow.pk,
                    "definitionSnapshot": {"nodes": []},
                }
            },
            plan={
                "businessFlow": {
                    "nodes": {
                        "interpret": {
                            "status": "succeeded",
                            "computeTaskId": str(task.pk),
                            "contractOutputs": [
                                {
                                    "name": "classification",
                                    "evidenceId": f"output-{output.pk}",
                                }
                            ],
                        }
                    }
                }
            },
        )
        ComputeImport.objects.create(
            output=output,
            status="ready",
            resource=result,
            requested_by=admin,
            request_source=f"workflow:{workflow.pk}",
        )
        previous_id = None
        if with_history:
            AgentWorkflow.objects.filter(pk=workflow.pk).update(
                created_at=datetime(2026, 11, 24, tzinfo=timezone.utc)
            )
            workflow.refresh_from_db()
            history = DataResource.objects.create(
                name="玛纳斯标准图",
                code="manans-standard",
                data_type="raster",
                storage_path="standard.tif",
                coordinate_system="EPSG:32645",
                maintainer=admin,
            )
            RasterDataset.objects.create(
                data_resource=history,
                status="ready",
                code="manans-standard",
                source_relative_path="standard.tif",
                raster_kind="categorical",
                bounds_4326=bounds,
                source_checksum_sha256="d" * 64,
            )
            for day, region in (
                ("2026-11-23", f"source-{raw.pk}"),
                ("2026-11-24", f"source-{raw.pk}"),
            ):
                product, _ = register_product(
                    admin,
                    {
                        **base,
                        "code": f"standard-{day}",
                        "name": "玛纳斯冰川标准图",
                        "scene": "glacier",
                        "resourceId": history.pk,
                        "registrationDate": day,
                        "sourceResourceIds": [raw.pk],
                        "referenceRole": "standard",
                        "quality": "passed",
                        "statistics": {"valid_pixels": 100},
                    },
                )
                product.metadata.update(
                    glacierTask=MANANS_STANDARD_TASK,
                    glacierRegion=region,
                    standardSource={"sourceSha256": "c" * 64, "resultSha256": "d" * 64},
                )
                product.save(update_fields=["metadata"])
                if day == "2026-11-23":
                    previous_id = product.pk
            match, proof = resolve_manans_registered(
                workflow, admin, SimpleNamespace(resource_id=raw.pk)
            )
            assert match.pk == history.pk and proof["baselineProductId"] == previous_id
            assert (
                proof["baselineImageId"] == raw.pk
                and proof["baselineBasis"] == "classification"
            )
            comparison = AlgorithmResource.objects.create(
                identifier="glacier-temporal-compare", name="变化", created_by=admin
            )
            compared = ComputeTask.objects.create(
                owner=admin,
                name="变化",
                status="succeeded",
                version=AlgorithmVersion.objects.create(
                    algorithm=comparison, version="1.4.0"
                ),
                idempotency_key="manans-compare",
                parameters={
                    "region": proof["region"],
                    "baseline_product_id": previous_id,
                    "baseline_date": "2026-11-23",
                    "baseline_basis": "classification",
                },
            )
            for key, resource in (
                ("current", result),
                ("baseline", history),
                ("baseline_image", raw),
            ):
                ComputeInput.objects.create(task=compared, key=key, resource=resource)
            ComputeOutput.objects.create(
                task=compared,
                key="coverage",
                kind="table",
                file_name="coverage.csv",
                path="coverage.csv",
                size_bytes=99,
                checksum="e" * 64,
                metadata={
                    "qualityCheck": {
                        **QUALITY,
                        "metrics": {
                            "comparisonStatus": "compared",
                            "commonAreaKm2": 0.008,
                            "changedPercent": 15,
                            "netClass1Km2": -0.001,
                            "netClass2Km2": None,
                            "netIceAreaKm2": -0.001,
                        },
                    }
                },
            )
            state(workflow)["nodes"]["compare"] = {
                "status": "succeeded",
                "computeTaskId": str(compared.pk),
            }
            workflow.save(update_fields=["plan"])
        else:
            match, proof = resolve_manans_registered(
                workflow, admin, SimpleNamespace(resource_id=raw.pk)
            )
            assert match is None and proof["reason"] == "no_prior"
        registered = publish_manans(workflow.pk, admin.pk)
        assert publish_manans(workflow.pk, admin.pk).pk == registered.pk
        registered.refresh_from_db()
        assert registered.acquired_on == date(2021, 9, 8)

    with project_scope(ProjectScope((project.pk,), project.pk, reader.pk)):
        item = next(
            row
            for row in official_snapshot(reader, "glacier")["items"]
            if row["id"] == registered.pk
        )
        assert (
            item["model"]["variant"] == MANANS_VARIANT
            and item["observedStart"] == "2021-09-08"
        )
        assert item["comparison"]["resource"]["id"] == raw.pk
        if with_history:
            assert item["glacierChange"]["baselineProductId"] == previous_id
            assert item["glacierChange"]["netIceAreaKm2"] == -0.001
        else:
            assert item["glacierChange"] is None
        values = {value["key"]: value for value in item["metrics"]}
        assert values["class_1_percent"]["label"] == "冰川占有效区"
        assert values["class_1_percent"]["value"] == 25
        assert values["class_2_percent"]["value"] is None
        assert values["ice_area_km2"]["value"] == 0.002
