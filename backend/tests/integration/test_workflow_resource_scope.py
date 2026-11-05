"""Business discovery and task-scoped access must agree without leaking packets."""

# ruff: noqa: F811

import uuid

import pytest
from django.core.exceptions import PermissionDenied

from apps.agent.models import Conversation, AgentRun, AgentWorkflow, WorkflowUpload
from apps.agent.resource_discovery import (
    discover_resources,
    resolve_discoverable_resource,
)
from apps.agent.workflow_resources import (
    resolve_generated_resource,
    resolve_run_resource,
    resolve_scenario_resource,
    resolve_upload_resource,
    resolve_workflow_resource,
)
from apps.catalog.models import DataResource
from apps.compute.models import ComputeImport, ComputeOutput, ComputeTask
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo  # noqa: F401

pytestmark = pytest.mark.django_db


def workflow(case, **values):
    return AgentWorkflow.objects.create(
        owner=case["owner"],
        goal="检查任务边界",
        model="mock",
        status="waiting_approval",
        idempotency_key=uuid.uuid4().hex,
        **values,
    )


def packet(case, source, **values):
    return DataResource.objects.create(
        name="测试材料",
        code="scope-" + uuid.uuid4().hex,
        data_type="table",
        source=source,
        owner_only=True,
        maintainer=case["owner"],
        **values,
    )


def upload(case, target=None):
    batch = uuid.uuid4().hex
    resource = packet(case, "workflow-upload:" + batch)
    item = WorkflowUpload.objects.create(
        owner=case["owner"],
        batch_id=batch,
        resource=resource,
        workflow=target,
        file_name="用户资料.csv",
        size_bytes=10,
        source="upload",
    )
    return resource, item


def test_unbound_attachment_requires_actual_batch_and_owner(demo):
    resource, item = upload(demo)
    assert (
        not discover_resources(demo["owner"], demo["policy"])
        .filter(pk=resource.pk)
        .exists()
    )
    assert (
        resolve_upload_resource(
            demo["owner"], demo["policy"], resource.pk, item.batch_id
        )
        == resource
    )
    with pytest.raises(PermissionDenied):
        resolve_upload_resource(
            demo["owner"], demo["policy"], resource.pk, uuid.uuid4().hex
        )
    with pytest.raises(PermissionDenied):
        resolve_upload_resource(
            demo["admin"], demo["policy"], resource.pk, item.batch_id
        )
    with pytest.raises(PermissionDenied):
        resolve_discoverable_resource(
            demo["owner"], demo["policy"], resource.pk, [resource.pk]
        )


def test_foreign_workflow_input_ids_cannot_grant_attachment_access(demo):
    own = workflow(demo)
    resource, item = upload(demo, own)
    own.resource_ids = [resource.pk]
    own.plan = {"uploadBatchId": item.batch_id, "uploadInputs": {"units": resource.pk}}
    own.save()
    assert (
        resolve_workflow_resource(demo["owner"], demo["policy"], resource.pk, own)
        == resource
    )
    other = workflow(demo, resource_ids=[resource.pk], plan=own.plan)
    with pytest.raises(PermissionDenied):
        resolve_workflow_resource(demo["owner"], demo["policy"], resource.pk, other)
    with pytest.raises(PermissionDenied):
        resolve_upload_resource(
            demo["owner"], demo["policy"], resource.pk, item.batch_id
        )


@pytest.mark.parametrize(
    "purpose,prefix",
    [
        ("frozen_rules", "geology-multi-frozen-rules:"),
        ("approved_changes", "geology-multi-approved:"),
        ("model_changes", "demo-changes:"),
    ],
)
def test_generated_packets_stay_with_their_task(demo, purpose, prefix):
    own = workflow(demo)
    resource = packet(
        demo,
        prefix + str(own.pk),
        storage_path=f"table/demo/workflows/{own.pk}/packet.csv",
    )
    own.plan = {purpose: resource.pk}
    own.save()
    assert (
        resolve_workflow_resource(demo["owner"], demo["policy"], resource.pk, own)
        == resource
    )
    assert (
        resolve_generated_resource(
            demo["owner"], demo["policy"], resource.pk, own, purpose
        )
        == resource
    )
    other = workflow(demo, resource_ids=[resource.pk], plan=own.plan)
    with pytest.raises(PermissionDenied):
        resolve_workflow_resource(demo["owner"], demo["policy"], resource.pk, other)
    with pytest.raises(PermissionDenied):
        resolve_generated_resource(
            demo["owner"], demo["policy"], resource.pk, other, purpose
        )
    with pytest.raises(PermissionDenied):
        resolve_discoverable_resource(demo["owner"], demo["policy"], resource.pk)


def test_registered_rules_are_only_a_scenario_rule_input(demo):
    rules = packet(demo, "管理员登记")
    rules.code = "geology-multi-rules-complete-20261105"
    rules.save()
    assert (
        resolve_scenario_resource(
            demo["owner"], demo["policy"], rules.pk, "geology_generic", "rules"
        )
        == rules
    )
    with pytest.raises(PermissionDenied):
        resolve_discoverable_resource(
            demo["owner"], demo["policy"], rules.pk, [rules.pk]
        )
    with pytest.raises(PermissionDenied):
        resolve_scenario_resource(
            demo["owner"], demo["policy"], rules.pk, "geology_generic", "units"
        )
    with pytest.raises(PermissionDenied):
        resolve_scenario_resource(
            demo["owner"], demo["policy"], rules.pk, "ecology_investigation", "rules"
        )


def test_ready_output_requires_real_workflow_step_not_claimed_id(demo):
    own = workflow(demo)
    task = ComputeTask.objects.create(
        owner=demo["owner"],
        version=demo["version"],
        name="检查",
        status="succeeded",
        idempotency_key=uuid.uuid4().hex,
        request_hash="a" * 64,
    )
    output = ComputeOutput.objects.create(
        task=task,
        key="issues",
        label="问题",
        kind="table",
        file_name="issues.csv",
        path="issues.csv",
        size_bytes=10,
        checksum="b" * 64,
    )
    resource = packet(demo, "compute-output:" + str(output.pk))
    record = ComputeImport.objects.create(
        output=output,
        requested_by=demo["owner"],
        name="检查输出",
        status="ready",
        resource=resource,
        request_source="workflow:" + str(own.pk),
    )
    own.resource_ids = [resource.pk]
    own.result_resource_ids = [resource.pk]
    own.save()
    with pytest.raises(PermissionDenied):
        resolve_workflow_resource(demo["owner"], demo["policy"], resource.pk, own)
    own.steps.create(
        sequence=1, kind="submit_operator", status="succeeded", compute_task_id=task.pk
    )
    assert (
        resolve_workflow_resource(demo["owner"], demo["policy"], resource.pk, own)
        == resource
    )
    record.status = "failed"
    record.save()
    with pytest.raises(PermissionDenied):
        resolve_workflow_resource(demo["owner"], demo["policy"], resource.pk, own)


def test_workflow_plan_cannot_expand_explicit_business_input_selection(demo):
    selected = DataResource.objects.create(
        name="手选业务数据", code="workflow-selected-input", data_type="table"
    )
    extra = DataResource.objects.create(
        name="计划另填业务数据", code="workflow-extra-input", data_type="table"
    )
    own = workflow(
        demo, resource_ids=[selected.pk], plan={"inputs": {"table": extra.pk}}
    )
    with pytest.raises(PermissionDenied):
        resolve_workflow_resource(demo["owner"], demo["policy"], extra.pk, own)
    own.resource_ids = [selected.pk, extra.pk]
    own.save(update_fields=["resource_ids"])
    assert (
        resolve_workflow_resource(demo["owner"], demo["policy"], extra.pk, own) == extra
    )


def test_archived_workflow_input_is_history_only_and_still_requires_acl(demo):
    resource = packet(demo, "用户上传", status="archived")
    own = workflow(
        demo, resource_ids=[resource.pk], plan={"inputs": {"table": resource.pk}}
    )
    assert (
        resolve_workflow_resource(
            demo["owner"], demo["policy"], resource.pk, own, history=True
        )
        == resource
    )
    with pytest.raises(PermissionDenied):
        resolve_workflow_resource(demo["owner"], demo["policy"], resource.pk, own)
    resource.maintainer = demo["admin"]
    resource.save(update_fields=["maintainer"])
    with pytest.raises(PermissionDenied):
        resolve_workflow_resource(
            demo["owner"], demo["policy"], resource.pk, own, history=True
        )


@pytest.mark.parametrize("history", [True, False])
def test_ready_workflow_import_survives_expiration_of_raw_output(demo, history):
    own = workflow(demo)
    task = ComputeTask.objects.create(
        owner=demo["owner"],
        version=demo["version"],
        name="已入库计算",
        status="succeeded",
        idempotency_key=uuid.uuid4().hex,
        request_hash="c" * 64,
    )
    output = ComputeOutput.objects.create(
        task=task,
        key="issues",
        label="问题",
        kind="table",
        file_name="expired-issues.csv",
        path="expired-issues.csv",
        size_bytes=10,
        checksum="d" * 64,
        expired=True,
    )
    resource = packet(demo, "compute-output:" + str(output.pk))
    record = ComputeImport.objects.create(
        output=output,
        requested_by=demo["owner"],
        name="独立入库输出",
        status="ready",
        resource=resource,
        request_source="workflow:" + str(own.pk),
    )
    own.steps.create(
        sequence=1, kind="submit_operator", status="succeeded", compute_task_id=task.pk
    )
    assert (
        resolve_workflow_resource(
            demo["owner"], demo["policy"], resource.pk, own, history=history
        )
        == resource
    )
    record.status = "failed"
    record.save(update_fields=["status"])
    with pytest.raises(PermissionDenied):
        resolve_workflow_resource(
            demo["owner"], demo["policy"], resource.pk, own, history=history
        )


def test_run_scope_uses_persisted_workflow_binding_and_manual_ceiling(demo):
    own = workflow(demo)
    resource, item = upload(demo, own)
    own.resource_ids = [resource.pk]
    own.plan = {"uploadBatchId": item.batch_id}
    own.save()
    conversation = Conversation.objects.create(owner=demo["owner"], mode="agent")
    run = AgentRun.objects.create(
        owner=demo["owner"],
        conversation=conversation,
        model="mock",
        prompt="检查",
        status="succeeded",
        research_workflow=own,
    )
    assert (
        resolve_run_resource(demo["owner"], demo["policy"], resource.pk, run)
        == resource
    )
    AgentRun.objects.filter(pk=run.pk).update(research_workflow=None)
    with pytest.raises(PermissionDenied):
        resolve_run_resource(demo["owner"], demo["policy"], resource.pk, run)
    business = DataResource.objects.create(
        name="用户演示数据", code="business-scope", data_type="table"
    )
    run.data_selection_mode = "manual"
    run.resource_ids = []
    run.save(update_fields=["data_selection_mode", "resource_ids"])
    with pytest.raises(PermissionDenied):
        resolve_run_resource(demo["owner"], demo["policy"], business.pk, run)


@pytest.mark.parametrize("binding", ["workflow", "upload_batch"])
@pytest.mark.parametrize("empty_selection", [True, False])
def test_bound_business_data_still_obeys_current_run_manual_ceiling(
    demo, binding, empty_selection
):
    business = DataResource.objects.create(
        name="工作流原始业务数据", code="bound-business", data_type="table"
    )
    selected = DataResource.objects.create(
        name="当前手选业务数据", code="selected-business", data_type="table"
    )
    bound = {}
    if binding == "workflow":
        bound["research_workflow"] = workflow(
            demo, resource_ids=[business.pk], plan={"inputs": {"table": business.pk}}
        )
    else:
        batch = uuid.uuid4().hex
        WorkflowUpload.objects.create(
            owner=demo["owner"],
            batch_id=batch,
            resource=business,
            file_name="目录数据",
            size_bytes=10,
            source="catalog",
        )
        bound["research_intent"] = {"_uploadBatchId": batch}
    conversation = Conversation.objects.create(owner=demo["owner"], mode="agent")
    run = AgentRun.objects.create(
        owner=demo["owner"],
        conversation=conversation,
        model="mock",
        prompt="检查",
        status="succeeded",
        data_selection_mode="manual",
        resource_ids=[] if empty_selection else [selected.pk],
        **bound,
    )
    with pytest.raises(PermissionDenied):
        resolve_run_resource(demo["owner"], demo["policy"], business.pk, run)
    # The same real binding remains usable after the user includes its input.
    run.resource_ids = [business.pk]
    run.save(update_fields=["resource_ids"])
    assert (
        resolve_run_resource(demo["owner"], demo["policy"], business.pk, run)
        == business
    )
