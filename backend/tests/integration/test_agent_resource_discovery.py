"""Business discovery never treats an arbitrary internal ID as authorization."""
# ruff: noqa: F811 - pytest fixtures are injected by name.

import json
import uuid

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied

from apps.agent.compute_tools import authorized_task, list_tasks
from apps.agent.models import (
    AgentComputeFollowup,
    AgentRun,
    AgentWorkflow,
    AgentWorkflowStep,
    Conversation,
    WorkflowUpload,
)
from apps.agent.policy import default_policy
from apps.agent.resource_discovery import (
    INTERNAL_SOURCE_PREFIXES,
    RESERVED_RULE_CODES,
    discover_resources,
    resolve_acl_resource,
)
from apps.agent.tools import execute, resolve_resource
from apps.catalog.models import DataResource
from apps.compute.models import (
    AlgorithmResource,
    AlgorithmVersion,
    ComputeImport,
    ComputeOutput,
    ComputeTask,
)
from apps.projects.context import project_scope
from apps.projects.models import ProjectMembership
from tests.integration.test_agent import new_run, setup_agent  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def env(setup_agent):
    env = setup_agent
    env["policy"] = default_policy()
    env["user"].user_permissions.add(
        *Permission.objects.filter(codename="view_own_task")
    )
    with project_scope(env["scope"]):
        algorithm = AlgorithmResource.objects.create(
            identifier="discovery-test", name="发现边界", created_by=env["user"]
        )
        env["version"] = AlgorithmVersion.objects.create(
            algorithm=algorithm,
            version="1",
            status="published",
            manifest={"agent": {"enabled": True}},
        )
        env["run"] = new_run(env)
        yield env


def resource(env, name="business", **kwargs):
    return DataResource.objects.create(
        name=name,
        code=name + "-" + uuid.uuid4().hex[:8],
        data_type="table",
        **kwargs,
    )


def imported(env, name="manual", key="summary", **task_options):
    task = ComputeTask.objects.create(
        owner=env["user"],
        version=env["version"],
        name=name,
        status="succeeded",
        idempotency_key=uuid.uuid4().hex,
        **task_options,
    )
    output = ComputeOutput.objects.create(
        task=task,
        key=key,
        label=key,
        kind="table",
        file_name=key + ".csv",
        path="unused.csv",
        size_bytes=1,
        checksum="a" * 64,
    )
    item = resource(
        env, name, is_compute_result=True, source="compute-output:" + str(task.id)
    )
    record = ComputeImport.objects.create(
        output=output,
        requested_by=env["user"],
        name=name,
        resource=item,
        status="ready",
    )
    return item, task, output, record


def workflow(
    env,
    item,
    task,
    output,
    *,
    stage="apply",
    status="succeeded",
    workflow_type="geology_multi_element_reasoning",
    declared_keys=None,
    identifier=None,
):
    if identifier is None:
        identifier = {
            ("ecology_investigation", "change"): "ndvi-change",
            ("ecology_investigation", "priority"): "ecology-priority",
            ("ecology_investigation", "early_ndvi"): "raster-ndvi",
            ("geology_correction", "edit"): "geology-edit",
            ("geology_age_correction", "edit"): "geology-age-edit",
            ("geology_map_review", "edit"): "geology-map-correct",
        }.get((workflow_type, stage), "geology-multi-" + stage)
    algorithm, _ = AlgorithmResource.objects.get_or_create(
        identifier=identifier, defaults={"name": identifier, "created_by": env["user"]}
    )
    declared_keys = (
        [output.key, "final_faults", "final_alterations", "hematite_corrected"]
        if declared_keys is None
        else declared_keys
    )
    version = AlgorithmVersion.objects.create(
        algorithm=algorithm,
        version=uuid.uuid4().hex,
        status="published",
        manifest={
            "identifier": identifier,
            "outputs": [{"key": key, "kind": "table"} for key in declared_keys],
        },
    )
    task.version = version
    task.save(update_fields=["version"])
    result = AgentWorkflow.objects.create(
        owner=env["user"],
        model="mock",
        goal="真实终端成果",
        status=status,
        workflow_type=workflow_type,
        idempotency_key=uuid.uuid4().hex,
        result_resource_ids=[item.id],
        plan={
            "stages": [
                {
                    "name": stage,
                    "identifier": identifier,
                    "status": "completed",
                    "taskId": str(task.id),
                    "outputs": [
                        {
                            "outputId": output.id,
                            "resourceId": item.id,
                            "key": output.key,
                            "checksum": output.checksum,
                        }
                    ],
                }
            ]
        },
    )
    AgentWorkflowStep.objects.create(
        workflow=result,
        sequence=1,
        kind="collect_results",
        status="succeeded",
        compute_task_id=task.id,
    )
    return result


def ids(env, user=None):
    return set(
        discover_resources(user or env["user"], env["policy"]).values_list(
            "id", flat=True
        )
    )


def test_sources_rules_and_flags_do_not_leak_to_any_discovery_or_direct_read(env):
    hidden = [
        resource(env, source=prefix + "old-marker")
        for prefix in INTERNAL_SOURCE_PREFIXES
    ]
    for code in RESERVED_RULE_CODES:
        item = resource(env)
        item.code = code
        item.save()
        hidden.append(item)
    hidden.append(resource(env, is_compute_result=True))
    hidden.append(resource(env, source="compute-output:orphan"))
    hidden.append(resource(env, source="workflow-report:invented"))
    item = resource(env, "inactive", status="inactive")
    hidden.append(item)
    assert ids(env) == {env["resource"].id}
    assert ids(env, env["admin"]) == {env["resource"].id}
    for item in hidden:
        with pytest.raises(PermissionDenied):
            resolve_resource(env["user"], env["policy"], item.id, [item.id])
    summary, _ = execute(env["run"], "summarize_resource_catalog", {})
    page, _ = execute(env["run"], "search_resources", {"limit": 2})
    presentation, _ = execute(env["run"], "present_resource_catalog", {})
    assert summary["total"] == page["total"] == presentation["summary"]["total"] == 1
    assert page["items"][0]["id"] == env["resource"].id


def test_upload_relation_hides_owned_attachment_but_catalog_reference_preserves_business(
    env,
):
    business, attachment = resource(env, "business"), resource(env, "attachment")
    for item, kind in ((business, "catalog"), (attachment, "upload")):
        WorkflowUpload.objects.create(
            owner=env["user"], batch_id=uuid.uuid4().hex, resource=item, source=kind
        )
    assert ids(env) == {env["resource"].id, business.id}
    assert (
        resolve_acl_resource(env["user"], env["policy"], attachment.id).id
        == attachment.id
    )


def test_only_ready_non_trial_real_imports_count_as_compute_results(env):
    item, _, _, record = imported(env)
    trial, _, _, _ = imported(env, "trial", trial=True)
    pending, _, _, pending_record = imported(env, "pending")
    pending_record.status = "queued"
    pending_record.save()
    assert item.id in ids(env)
    assert trial.id not in ids(env) and pending.id not in ids(env)
    item.is_compute_result = False
    item.save()
    summary, _ = execute(env["run"], "summarize_resource_catalog", {})
    page, _ = execute(env["run"], "search_resources", {"category": "compute_results"})
    assert summary["counts"] == {"compute_results": 1, "uploaded_data": 1}
    assert page["total"] == 1 and page["items"][0]["isComputeResult"] is True
    record.status = "failed"
    record.save()
    assert item.id not in ids(env)


@pytest.mark.parametrize(
    ("stage", "key", "allowed"),
    [
        ("apply", "lithology", True),
        ("apply", "final_faults", True),
        ("apply", "hematite_corrected", True),
        ("relations", "intersections", True),
        ("prospect", "after_zones", True),
        ("check", "issues", False),
        ("apply", "changes", False),
        ("apply", "faults", False),
    ],
)
def test_workflow_terminal_keys_require_a_completed_real_chain(
    env, stage, key, allowed
):
    item, task, output, record = imported(env, key=key)
    bound = workflow(env, item, task, output, stage=stage)
    # Manual approval may leave this empty; the actual step still proves process scope.
    assert record.request_source == ""
    assert (item.id in ids(env)) is allowed
    output.expired = True
    output.save(update_fields=["expired"])
    assert (item.id in ids(env)) is allowed
    bound.status = "waiting_compute"
    bound.save()
    assert item.id not in ids(env)


@pytest.mark.parametrize(
    "broken",
    ["task_owner", "step", "result_ids", "output_id", "checksum", "resource_id"],
)
def test_terminal_metadata_alone_cannot_promote_unrelated_process_material(env, broken):
    item, task, output, _ = imported(env, key="lithology")
    bound = workflow(env, item, task, output)
    if broken == "task_owner":
        task.owner = env["other"]
        task.save()
    elif broken == "step":
        bound.steps.all().delete()
        record = output.import_record
        record.request_source = "workflow:" + str(bound.id)
        record.save()
    elif broken == "result_ids":
        bound.result_resource_ids = []
    else:
        entry = bound.plan["stages"][0]["outputs"][0]
        entry[
            {"output_id": "outputId", "resource_id": "resourceId"}.get(broken, broken)
        ] = 999
    bound.save()
    assert item.id not in ids(env)


def test_report_requires_real_saved_metadata_and_completed_workflow(env):
    from apps.agent.workflow_reports import _paths, _source
    from apps.compute.packages import checksum

    bound = AgentWorkflow.objects.create(
        owner=env["user"],
        model="mock",
        goal="报告",
        status="succeeded",
        idempotency_key="report",
    )
    path, metadata_path, relative = _paths(bound)
    path.parent.mkdir(parents=True)
    path.write_text("# 实际报告\n", encoding="utf-8")
    item = resource(
        env,
        "report",
        is_compute_result=True,
        source=_source(bound),
        storage_path="table/" + relative,
        maintainer=env["user"],
        quality_note="SHA256: " + checksum(path),
    )
    metadata = {
        "schemaVersion": 1,
        "fileName": "report.md",
        "label": "报告",
        "sizeBytes": path.stat().st_size,
        "checksum": checksum(path),
        "resourceId": item.id,
    }
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    assert item.id in ids(env)
    path.write_text("被修改", encoding="utf-8")
    assert item.id not in ids(env)


def test_revoked_membership_and_type_policy_still_apply(env):
    assert env["resource"].id in ids(env)
    assert not discover_resources(env["user"], {"dataTypes": ["raster"]}).exists()
    ProjectMembership.objects.filter(project=env["project"], user=env["user"]).delete()
    assert ids(env) == set()


def test_plain_task_tools_do_not_rediscover_trial_or_other_workflow_tasks(env):
    _, normal, _, _ = imported(env, "normal")
    _, trial, _, _ = imported(env, "trial", trial=True)
    internal, process, output, _ = imported(env, "process", key="issues")
    workflow(env, internal, process, output, stage="check")
    listed, _ = list_tasks(env["run"], env["user"], env["policy"], {})
    assert [item["taskId"] for item in listed["items"]] == [str(normal.id)]
    for task in (normal, trial, process):
        with pytest.raises(PermissionDenied):
            authorized_task(env["user"], task.id, env["policy"], run=env["run"])


def test_task_runtime_requires_real_same_conversation_binding(env):
    _, task, _, _ = imported(env)
    other_conversation = Conversation.objects.create(owner=env["user"], mode="agent")
    other_run = AgentRun.objects.create(
        conversation=other_conversation,
        owner=env["user"],
        model="mock",
        prompt="另一会话",
        status="succeeded",
        idempotency_key="other-task",
    )
    followup = AgentComputeFollowup.objects.create(run=other_run, task=task)
    with pytest.raises(PermissionDenied, match="当前会话"):
        authorized_task(env["user"], task.id, env["policy"], run=env["run"])
    followup.run = env["run"]
    followup.save()
    assert (
        authorized_task(env["user"], task.id, env["policy"], run=env["run"]).id
        == task.id
    )


def test_query_output_read_and_import_reject_an_unbound_normal_task(env):
    from apps.agent.compute_result_tools import read_output
    from apps.agent.compute_tools import import_result, query_task

    _, task, output, _ = imported(env)
    policy = {**env["policy"], "operatorEnabled": True}
    for handler, args in (
        (query_task, {"taskId": str(task.id)}),
        (read_output, {"outputId": output.id}),
        (import_result, {"outputId": output.id}),
    ):
        with pytest.raises(PermissionDenied, match="当前会话"):
            handler(env["run"], env["user"], policy, args)


def test_structural_internal_roles_stay_hidden_after_source_and_flag_edits(env):
    working = resource(env, "working")
    frozen = resource(env, "frozen")
    approved = resource(env, "approved")
    changes = resource(env, "changes")
    AgentWorkflow.objects.create(
        owner=env["user"],
        model="mock",
        goal="结构关系",
        status="failed",
        idempotency_key="structure",
        resource_ids=[env["resource"].id],
        plan={
            "workingCopies": {"lithology": working.id},
            "frozen_rules": frozen.id,
            "approved_changes": approved.id,
            "model_changes": changes.id,
        },
    )
    assert ids(env) == {env["resource"].id}


def test_unprocessed_rasters_stay_hidden_but_raw_retention_keeps_ready_imports(env):
    from apps.raster.models import RasterDataset

    raster = resource(env, "raster")
    raster.data_type = "raster"
    raster.save()
    assert raster.id not in ids(env)
    dataset = RasterDataset.objects.create(
        data_resource=raster,
        name="栅格",
        code="readiness",
        source_relative_path="test.tif",
        status="processing",
    )
    assert raster.id not in ids(env)
    dataset.status = "ready"
    dataset.save()
    assert raster.id in ids(env)
    computed, _, output, record = imported(env, "expired")
    output.expired = True
    output.save()
    assert computed.id in ids(env)
    record.status = "queued"
    record.save(update_fields=["status"])
    assert computed.id not in ids(env)


def test_algorithm_discovery_omits_disabled_versions_and_empty_algorithms(env):
    from apps.agent.tools import _algorithm_list

    hidden = AlgorithmResource.objects.create(
        identifier="hidden", name="隐藏算法", created_by=env["user"]
    )
    AlgorithmVersion.objects.create(
        algorithm=hidden,
        version="1",
        status="published",
        manifest={"agent": {"enabled": False}},
    )
    result = _algorithm_list(env["user"])
    assert [item["id"] for item in result["items"]] == [env["version"].algorithm_id]
    assert result["items"][0]["versions"][0]["agentEnabled"] is True


@pytest.mark.parametrize(
    "workflow_type,stage,key,allowed",
    [
        ("ecology_investigation", "change", "change", True),
        ("ecology_investigation", "change", "candidates", True),
        ("ecology_investigation", "priority", "priority", True),
        ("ecology_investigation", "priority", "statistics", True),
        ("ecology_investigation", "early_ndvi", "ndvi", False),
        ("ecology_investigation", "change", "statistics", False),
        ("ecology_investigation", "apply", "lithology", False),
        ("geology_correction", "edit", "corrected", True),
        ("geology_age_correction", "edit", "corrected", True),
        ("geology_map_review", "edit", "corrected", True),
        ("geology_map_review", "edit", "changes_map", True),
        ("geology_map_review", "edit", "changes", False),
    ],
)
def test_workflow_family_and_actual_stage_define_terminal_outputs(
    env, workflow_type, stage, key, allowed
):
    item, task, output, _ = imported(env, key=key)
    workflow(env, item, task, output, workflow_type=workflow_type, stage=stage)
    assert (item.id in ids(env)) is allowed


@pytest.mark.parametrize(
    "key,declared,allowed",
    [
        ("faults", ["faults"], True),
        ("faults", ["faults", "final_faults"], False),
        ("alterations", ["alterations"], True),
        ("alterations", ["alterations", "final_alterations"], False),
        ("alterations", ["alterations", "hematite_corrected"], False),
    ],
)
def test_legacy_apply_terminal_fallback_uses_its_actual_manifest(
    env, key, declared, allowed
):
    item, task, output, _ = imported(env, key=key)
    bound = workflow(env, item, task, output, declared_keys=declared)
    assert (item.id in ids(env)) is allowed
    item.source = "workflow-working:" + str(bound.id) + ":calculation"
    item.save(update_fields=["source"])
    assert item.id not in ids(env)


@pytest.mark.parametrize(
    "broken", ["algorithm", "manifest", "declaration", "stage", "family"]
)
def test_terminal_name_cannot_override_algorithm_manifest_or_workflow_type(env, broken):
    item, task, output, _ = imported(env, key="priority")
    bound = workflow(
        env, item, task, output, workflow_type="ecology_investigation", stage="priority"
    )
    version = task.version
    if broken == "algorithm":
        version.algorithm.identifier = "unrelated-priority"
        version.algorithm.save()
    elif broken == "manifest":
        version.manifest["identifier"] = "unrelated-priority"
    elif broken == "declaration":
        version.manifest["outputs"] = []
    elif broken == "stage":
        bound.plan["stages"][0]["identifier"] = "unrelated-priority"
    else:
        bound.workflow_type = "hyperspectral_interpretation"
    version.save()
    bound.save()
    assert item.id not in ids(env)


def test_previous_round_private_input_is_history_only_and_really_task_bound(env):
    from apps.compute.models import ComputeInput
    from apps.agent.workflow_resources import resolve_workflow_resource

    with project_scope(env["scope"]):
        saved = AgentWorkflow.objects.create(
            owner=env["user"],
            workflow_type="geology_generic",
            model="mock",
            idempotency_key=uuid.uuid4().hex,
            plan={"inputs": {}},
            resource_ids=[],
        )
        _, task, _, _ = imported(env, "prior-round")
        packet = resource(
            env,
            "prior-approved",
            source=f"geology-multi-approved:{saved.id}",
            owner_only=True,
            maintainer=env["user"],
        )
        ComputeInput.objects.create(task=task, key="approved_changes", resource=packet)
        with pytest.raises(PermissionDenied):
            resolve_workflow_resource(
                env["user"], env["policy"], packet.id, saved, history=True
            )
        AgentWorkflowStep.objects.create(
            workflow=saved,
            sequence=1,
            kind="submit_operator",
            compute_task_id=task.id,
            status="succeeded",
        )
        assert (
            resolve_workflow_resource(
                env["user"], env["policy"], packet.id, saved, history=True
            ).id
            == packet.id
        )
        with pytest.raises(PermissionDenied):
            resolve_workflow_resource(env["user"], env["policy"], packet.id, saved)
