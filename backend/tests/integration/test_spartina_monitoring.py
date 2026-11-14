"""RF products use actual imports; related data keeps project/resource ACLs."""

import pytest
from apps.compute.models import ComputeImport, ComputeOutput
from apps.ecology.monitoring import monitoring_snapshot
from apps.ecology.spartina import register_import, normalize_extraction
from apps.projects.context import project_scope
from apps.projects.features import set_feature
from apps.projects.models import ProjectFeature
from tests.integration.test_landcover_monitoring import imported  # noqa: F401
from tests.integration.test_compute import setup_compute  # noqa: F401

# ruff: noqa: F811


@pytest.fixture
def rf_import(imported):
    env, task, source, record = imported
    with project_scope(env["scope"]):
        algorithm = task.version.algorithm
        algorithm.identifier = "spartina-rf-infer"
        type(algorithm)._base_manager.filter(pk=algorithm.pk).update(
            identifier=algorithm.identifier
        )
        set_feature(
            env["admin"],
            ProjectFeature.objects.get(key="ecology_monitor"),
            project=env["project"],
            enabled=True,
            config={
                "title": "互花米草",
                "source": "remote_sensing_products",
                "scenes": ["spartina"],
                "initialView": {
                    "center": [121.92, 31.24],
                    "zoom": 0.3,
                    "regionZoom": 11,
                },
            },
        )
        facts = {
            "method": "RF",
            "inputPeriods": ["2025-03", "2025-08", "2025-12"],
            "bounds": [121.9, 31.2, 122, 31.3],
            "validPixelCount": 100,
            "targetPixelCount": 20,
            "sklearnVersion": "1.9.1",
            "modelSha256": "b" * 64,
            "statistics": {
                "area_ha": 2.0,
                "valid_area_km2": 0.1,
                "coverage_percent": 20.0,
                "patch_count": 1,
            },
        }
        output = record.output
        output.metadata = {**output.metadata, "knowledgeFacts": {"spartina": facts}}
        output.save()
        yield env, task, source, record


def test_rf_import_keeps_real_provenance_and_remains_idempotent(rf_import):
    env, task, source, record = rf_import
    with project_scope(env["scope"]):
        product, created = register_import(record.pk)
        assert created
        assert register_import(record.pk)[1] is False
        item = monitoring_snapshot(env["owner"], "spartina")["items"][0]
        assert item["resourceId"] == record.resource_id
        assert item["extraction"]["method"] == "RF"
        assert item["statistics"]["coverage_percent"] == 20
        assert item["provenance"]["taskId"] == str(task.pk)
        source.status = "inactive"
        source.save()
        assert monitoring_snapshot(env["owner"], "spartina")["items"] == []


def test_probability_attachment_must_be_accessible_and_from_same_task(rf_import):
    from apps.catalog.models import DataResource

    env, task, _, record = rf_import
    with project_scope(env["scope"]):
        register_import(record.pk)
        output = ComputeOutput.objects.create(
            task=task,
            key="probability",
            kind="raster",
            label="概率图",
            path="probability.tif",
            file_name="probability.tif",
            checksum="a" * 64,
            size_bytes=100,
            metadata={},
        )
        resource = DataResource.objects.create(
            name="私有概率",
            code="private-probability",
            data_type="raster",
            storage_path="probability.tif",
            owner_only=True,
            maintainer=env["outsider"],
            is_compute_result=True,
        )
        ComputeImport.objects.create(
            output=output,
            requested_by=env["owner"],
            resource=resource,
            status="ready",
        )
        assert (
            monitoring_snapshot(env["owner"], "spartina")["items"][0]["attachments"]
            == []
        )
        resource.owner_only = False
        resource.save()
        assert (
            monitoring_snapshot(env["owner"], "spartina")["items"][0]["attachments"][0][
                "resource"
            ]["id"]
            == resource.pk
        )


def test_extraction_rejects_inconsistent_counts():
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        normalize_extraction({"method": "RF"})


def test_rf_flow_publishes_three_seasons_as_one_operator_contract(setup_compute):
    import json
    from pathlib import Path
    from apps.compute.packages import validate_manifest
    from apps.business_flows.definitions import normalize_definition
    from apps.business_flows.spartina import definition
    from apps.projects.context import ProjectScope

    env = setup_compute
    version = env["version"]
    version.manifest = validate_manifest(
        json.loads(
            (
                Path(__file__).resolve().parents[3]
                / "examples/compute/spartina-rf/operator.yaml"
            ).read_text()
        )
    )
    version.save()
    with project_scope(
        ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)
    ):
        spec = normalize_definition(definition(version.pk))
    assert spec["executionMode"] == "main_agent"
    assert [row["key"] for row in spec["inputRequirements"]] == [
        "march",
        "august",
        "december",
    ]
    operators = [row for row in spec["nodes"] if row["kind"] == "operator"]
    assert len(operators) == 1
    assert set(operators[0]["contract"]["importOutputs"]) == {
        "classification",
        "probability",
        "statistics",
        "original",
    }
