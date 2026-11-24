import csv
from io import BytesIO
from runpy import run_path
import shutil

import geopandas as gpd
import pytest
from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import UploadedFile

from apps.agent.hermes_tools import execute
from apps.agent.models import AgentPolicy, HermesSession
from apps.business_flows.builtins import geology_definition
from apps.business_flows.catalog import register_flow
from apps.catalog.models import DataResource
from apps.compute.models import AlgorithmResource, ComputeImport, ComputeTask
from apps.compute.packages import checksum
from apps.compute.runtime import script_isolation_status
from apps.compute.views import store_version
from apps.compute.worker import process_import, run_task, task_scope
from apps.core.storage import app_path, table_data_path, vector_geopackage_path
from apps.projects.context import ProjectScope, project_scope
from apps.raster.services.importer import import_raster_file
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.unit.test_geology_multi_algorithms import fixture as geology_fixture

pytestmark = pytest.mark.django_db


def prepare_sample(env, tmp_path):
    user, project = env["owner"], env["project"]
    user.user_permissions.add(
        *Permission.objects.filter(
            codename__in=[
                "use_local_model",
                "use_data_agent",
                "query_data",
                "download_algorithm",
            ]
        )
    )
    project.code = "02"
    project.save(update_fields=["code"])
    AgentPolicy.objects.create(pk=1, value={"operatorEnabled": True})
    scope = ProjectScope((project.id,), project.id, user.id)
    synthetic = tmp_path / "geology"
    synthetic.mkdir()
    initial, _ = geology_fixture(synthetic)
    build = run_path(
        str(settings.PROGRAM_ROOT / "examples/compute/geology-multi-core/build.py")
    )["build"]

    with project_scope(scope):
        session = HermesSession.objects.create(
            owner=user, mode="agent", title="地质样例"
        )
        register_flow(
            env["admin"],
            {
                "code": "geology-logic-reasoning",
                "name": "逻辑推理",
                "description": "根据岩性、结构和蚀变资料复核图面。",
                "definition": geology_definition(main_agent=True),
            },
        )
        inputs = {}
        database = vector_geopackage_path()
        database.parent.mkdir(parents=True)
        for key in ("lithology", "faults", "coverage"):
            frame = gpd.read_file(initial.inputs[key])
            frame.to_file(database, layer=key, driver="GPKG")
            inputs[key] = DataResource.objects.create(
                name=key,
                code=key,
                data_type="vector",
                file_format="GPKG",
                storage_path=key,
                item_count=len(frame),
                maintainer=user,
            ).pk
        for key in ("hematite", "chlorite", "hydromica", "calcite", "dolomite"):
            inputs[key] = import_raster_file(
                initial.inputs[key],
                name=key,
                uploader_id=user.pk,
                native_result=True,
            ).data_resource_id
        source = table_data_path("rules.csv")
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(initial.inputs["rules"], source)
        # Exercise an encoding difference within one JSON cell.
        if script_isolation_status()["available"]:
            with source.open(encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                rules = list(reader)
                fields = reader.fieldnames
            rules[0]["rule_json"] = "\ufeff" + rules[0]["rule_json"]
            with source.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rules)
        inputs["rules"] = DataResource.objects.create(
            name="样例地质规则",
            code="geology-multi-rules-sample",
            data_type="table",
            file_format="CSV",
            storage_path="table/rules.csv",
            maintainer=user,
        ).pk
        versions = {}
        for suffix in ("check", "apply", "relations", "prospect"):
            identifier = "geology-multi-" + suffix
            algorithm = AlgorithmResource.objects.create(
                identifier=identifier,
                name=identifier,
                created_by=env["admin"],
            )
            package = build(identifier)
            version = store_version(
                algorithm,
                UploadedFile(
                    BytesIO(package), name=identifier + ".zip", size=len(package)
                ),
            )
            version.status = "published"
            version.runtime_digest = "sha256:" + "a" * 64
            version.save(update_fields=["status", "runtime_digest"])
            versions[suffix] = version

    return session, scope, inputs, versions


def test_hermes_geology_retries_and_composes_published_operators(
    setup_compute,  # noqa: F811
    tmp_path,
):
    session, scope, inputs, versions = prepare_sample(setup_compute, tmp_path)

    def tool(name, args=None, **kwargs):
        return execute(session, name, args or {}, "geology-journey", **kwargs)

    def submit(stage, data, *, label=None, edits=None, retry_of=None, reuse_copy=None):
        payload = {
            "versionId": versions[stage].pk,
            "name": label or stage,
            "inputs": data,
            "parameters": {"working_epsg": 32646},
        }
        if edits:
            payload["operatorEdits"] = edits
        if retry_of:
            payload["retryOf"] = retry_of
        if reuse_copy:
            payload["reuseOperatorCopyFrom"] = reuse_copy
        receipt = tool("submit_research_compute", payload)
        with project_scope(scope):
            task = ComputeTask.objects.get(pk=receipt["taskId"])
        with task_scope(task):
            run_task(task)
        return tool("get_research_compute", {"taskId": receipt["taskId"]})

    def output_of(result, key):
        assert result["status"] == "succeeded", (
            key,
            result["error"],
            result.get("failure"),
        )
        return next(output for output in result["outputs"] if output["key"] == key)

    def reuse(result, key):
        output = output_of(result, key)
        receipt = tool("register_research_output", {"outputId": output["id"]})
        with project_scope(scope):
            record = ComputeImport.objects.get(pk=receipt["importId"])
        with task_scope(record.output.task):
            process_import(record)
        record.refresh_from_db()
        assert record.status == "ready", record.error
        return record.resource_id

    workflow = tool("get_research_workflow", {"name": "逻辑推理"})
    assert workflow["domainSkill"] == "geology-research"
    assert (
        tool("list_research_geology_rules")["items"][0]["resourceId"] == inputs["rules"]
    )
    first = submit("check", inputs)
    edits = None
    retry_of = None
    if script_isolation_status()["available"]:
        assert first["status"] == "failed", first
        assert (
            first["failure"]["details"].get("sourceLocation", {}).get("file")
            == "multi_io.py"
        ), (first["error"], first["failure"])
        assert (
            "multi_io.py"
            in tool("inspect_research_operator", {"versionId": versions["check"].pk})[
                "files"
            ]
        )
        edits = [
            {
                "file": "multi_io.py",
                "before": 'json.loads(row["rule_json"])',
                "after": 'json.loads(row["rule_json"].lstrip("\\ufeff"))',
            }
        ]
        retry_of = first["taskId"]
        first = submit("check", inputs, edits=edits, retry_of=retry_of)
        assert first["operatorCopy"]["sourceSha256"] == versions["check"].checksum
        current = tool(
            "inspect_research_operator",
            {
                "taskId": first["taskId"],
                "file": "multi_io.py",
                "offset": 180,
            },
        )
        assert edits[0]["after"] in current["source"]

    issues = output_of(first, "issues")
    read = tool("read_research_output", {"outputId": issues["id"]})
    rows = [
        dict(zip(read["columns"], item, strict=True))
        if isinstance(item, list)
        else item
        for item in read["rows"]
    ]
    issue = next(
        row for row in rows if row["feature_id"] == "G4" and row["rule_id"] == "L-03"
    )
    choices = {
        "checkTaskId": first["taskId"],
        "actions": [
            {
                "issueId": issue["issue_id"],
                "action": "set_code",
                "reason": "按区域地层对应关系修正代号",
            },
        ],
    }
    review = tool("prepare_research_geology_changes", choices)
    assert "G4" in review["approvalSummary"]
    approval = tool(
        "prepare_research_geology_changes",
        choices,
        approval_digest=review["approvalDigest"],
    )
    assert tool("prepare_research_geology_changes", choices) == approval
    apply = submit(
        "apply",
        {
            **inputs,
            "issues": reuse(first, "issues"),
            "approved_changes": approval["resourceId"],
        },
        edits=edits,
    )
    assert output_of(apply, "lithology")["kind"] == "vector"
    corrected = {**inputs, "lithology": reuse(apply, "lithology")}
    after = submit("check", corrected, label="复核派生图件", edits=edits)
    checked = tool(
        "read_research_output", {"outputId": output_of(after, "issues")["id"]}
    )
    assert checked["total"] < read["total"]

    relation_inputs = {key: corrected[key] for key in ("faults", "coverage", "rules")}
    relations = submit(
        "relations",
        relation_inputs,
        reuse_copy=first["taskId"] if edits else None,
    )
    intersection = reuse(relations, "intersections")
    prospect = submit(
        "prospect", {**corrected, "intersections": intersection}, edits=edits
    )
    assert output_of(prospect, "statistics")["kind"] == "table"
    assert output_of(prospect, "prospect_support")["kind"] == "raster"
    assert all(
        checksum(app_path(v.package_path)) == v.checksum for v in versions.values()
    )
