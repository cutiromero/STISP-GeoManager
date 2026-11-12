"""All flows share real compute admission, import, control and input isolation."""

from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied

from apps.agent.models import AgentWorkflowStep
from apps.agent.policy import require_access
from apps.business_flows import catalog, runtime
from apps.business_flows.builtins import source_summary_definition
from apps.business_flows.input_preparation import advance_inputs
from apps.compute.models import ComputeTask, ComputeImport
from apps.compute.packages import ComputeError
from apps.compute.worker import process_import, task_scope
from apps.projects.context import project_scope
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_business_flow_operator_runtime import (  # noqa: F401
    operators,
    finish_task,
)

# ruff: noqa: F811
pytestmark = pytest.mark.efficiency


@pytest.fixture
def adapted(operators):
    env = operators
    version = env["version"]
    manifest = deepcopy(version.manifest)
    output = next(row for row in manifest["outputs"] if row["kind"] == "table")
    manifest["inputAdapter"] = {
        "inputKey": "table",
        "outputKey": output["key"],
        "sourceKind": "table",
        "targetKind": "table",
        "targetSemantics": "regional_statistics_v1",
        "outputFields": ["region", "value"],
    }
    version.manifest = manifest
    version.save(update_fields=["manifest"])
    definition = source_summary_definition()
    definition["inputRequirements"][0].update(
        semanticType="regional_statistics_v1", requiredFields=["region", "value"]
    )
    with project_scope(env["scope"]):
        _, flow = catalog.register_flow(
            env["admin"],
            {
                "code": "adapt-" + uuid4().hex[:8],
                "name": "区域统计业务流",
                "definition": definition,
            },
        )
        policy = require_access(env["owner"], "agent")
        body = {
            "model": "mock",
            "inputs": {"source": env["resource"].pk},
            "inputAdapters": {
                "source": {
                    "versionId": version.pk,
                    "parameters": env["body"]["parameters"],
                }
            },
            "idempotencyKey": uuid4().hex,
        }
        _, _, preview = runtime._inputs(
            env["owner"], flow.definition, body, policy, preview=True
        )
        assert preview["ready"] and preview["items"][0]["status"] == "convert"
        assert not ComputeTask.objects.exists(), "Preflight must never compute"
        workflow = runtime.start_flow(env["owner"], flow, body)
    return {
        **env,
        "workflow": workflow,
        "policy": policy,
        "definition": definition,
        "body": body,
    }


def prepare(env):
    workflow = env["workflow"]
    workflow.refresh_from_db()
    with project_scope(env["scope"]):
        runtime.authorize(env["owner"], workflow)
        return advance_inputs(workflow, env["owner"], env["policy"])


def test_conversion_queue_is_idempotent_and_import_is_workflow_private(adapted):
    env = adapted
    source = env["resource"]
    before = source.updated_at
    with patch(
        "apps.business_flows.input_preparation.submit",
        wraps=__import__("apps.compute.services", fromlist=["submit"]).submit,
    ) as submit:
        assert prepare(env) is False
        assert prepare(env) is False
        assert submit.call_count == 1
    workflow = env["workflow"]
    with project_scope(env["scope"]):
        assert ComputeTask.objects.count() == 1
        task = ComputeTask.objects.get()
        assert task.input_records.get().resource_id == source.pk
        assert workflow.operator_steps == 1
        output = finish_task(env, task.pk, "A")
    assert prepare(env) is False
    assert prepare(env) is False
    with project_scope(env["scope"]):
        assert ComputeImport.objects.count() == 1
        record = ComputeImport.objects.get(output=output)
        with task_scope(output.task):
            process_import(record)
        record.refresh_from_db()
        assert record.status == "ready", record.error
    assert prepare(env) is True
    workflow.refresh_from_db()
    assert workflow.plan["inputAdaptationComplete"] is True
    with project_scope(env["scope"]):
        workflow.refresh_from_db()
        prepared = record.resource
        prepared.refresh_from_db()
        assert workflow.plan["inputs"]["source"] == prepared.pk != source.pk
        assert prepared.owner_only and prepared.source.startswith(
            f"workflow-working:{workflow.pk}:input-adapter:"
        )
        assert len(workflow.steps.filter(kind="submit_operator")) == 1
        assert runtime.authorize(env["owner"], workflow)
    source.refresh_from_db()
    assert source.updated_at == before and source.storage_path == "samples"
    with patch("apps.business_flows.input_preparation.submit") as submit:
        assert prepare(env) is True
        submit.assert_not_called()


def test_revoked_source_stops_before_conversion_and_cancel_is_still_available(adapted):
    env = adapted
    source = env["resource"]
    source.owner_only = True
    source.maintainer = env["outsider"]
    source.save(update_fields=["owner_only", "maintainer"])
    with pytest.raises(PermissionDenied):
        prepare(env)
    with project_scope(env["scope"]):
        assert not ComputeTask.objects.exists()
        runtime.control_flow(env["owner"], env["workflow"], "cancel")
    env["workflow"].refresh_from_db()
    assert env["workflow"].cancel_requested


def test_changed_version_or_source_cannot_run_a_stale_plan(adapted):
    env = adapted
    env["version"].checksum = "f" * 64
    env["version"].save(update_fields=["checksum"])
    with pytest.raises(PermissionDenied, match="冻结"):
        prepare(env)
    with project_scope(env["scope"]):
        assert not ComputeTask.objects.exists()


def test_cancel_and_operator_budget_block_before_submission(adapted):
    env = adapted
    workflow = env["workflow"]
    workflow.operator_steps = workflow.max_operator_steps
    workflow.save(update_fields=["operator_steps"])
    from apps.agent.business_flow_context import ContextReviewRequired

    with pytest.raises(ContextReviewRequired, match="额度"):
        prepare(env)
    with project_scope(env["scope"]):
        runtime.control_flow(env["owner"], workflow, "cancel")
        assert not ComputeTask.objects.exists()
    with pytest.raises(ComputeError, match="停止"):
        prepare(env)


def test_failed_conversion_keeps_original_and_does_not_resubmit(adapted):
    env = adapted
    assert prepare(env) is False
    with project_scope(env["scope"]):
        ComputeTask.objects.update(status="failed", error="来源无法转换")
    for _ in range(2):
        with pytest.raises(ComputeError, match="来源无法转换"):
            prepare(env)
    with project_scope(env["scope"]):
        assert ComputeTask.objects.count() == 1
        assert AgentWorkflowStep.objects.filter(kind="submit_operator").count() == 1
    env["resource"].refresh_from_db()
    assert env["resource"].status == "active"


def test_geology_family_is_frozen_as_a_set_and_rechecks_revocation(operators):
    from types import SimpleNamespace
    from apps.agent.alteration_stack import supports_stack
    from apps.agent.demo_workflow import _versions
    from apps.compute.models import AlgorithmResource, AlgorithmVersion

    env = operators
    workflow = SimpleNamespace(plan={})
    identifiers = [
        "geology-multi-" + name for name in ("check", "apply", "relations", "prospect")
    ]
    versions = {}
    with project_scope(env["scope"]):
        for index, identifier in enumerate(identifiers):
            algorithm = AlgorithmResource.objects.create(
                identifier=identifier, name=identifier, created_by=env["admin"]
            )
            manifest = deepcopy(env["version"].manifest)
            if not identifier.endswith("relations"):
                manifest["inputs"] = [{"key": "alteration_stack", "kind": "raster"}]
            versions[identifier] = AlgorithmVersion.objects.create(
                algorithm=algorithm,
                version="1.0.0",
                manifest=manifest,
                checksum=str(index) * 64,
                status="published",
            )
        assert supports_stack(workflow, env["owner"])
        frozen = deepcopy(workflow.plan["preparedAlgorithmFamily"])
        selected = versions[identifiers[0]]
        AlgorithmVersion.objects.create(
            algorithm=selected.algorithm,
            version="2.0.0",
            manifest=selected.manifest,
            checksum="f" * 64,
            status="published",
        )
        graph = [
            (str(index), identifier, {}) for index, identifier in enumerate(identifiers)
        ]
        assert {
            key: {k: row[k] for k in ("versionId", "checksum")}
            for key, row in _versions(workflow, graph).items()
        } == frozen
        selected.status = "archived"
        selected.save(update_fields=["status"])
        with pytest.raises(ComputeError, match="不可调用"):
            _versions(workflow, graph)


def test_two_roles_share_one_identical_conversion_but_keep_their_bindings(adapted):
    env = adapted
    definition = deepcopy(env["definition"])
    definition["inputRequirements"].append(
        {
            **definition["inputRequirements"][0],
            "key": "context",
            "label": "背景统计",
        }
    )
    body = deepcopy(env["body"])
    body["inputs"]["context"] = env["resource"].pk
    body["inputAdapters"]["context"] = deepcopy(body["inputAdapters"]["source"])
    body["idempotencyKey"] = uuid4().hex
    with project_scope(env["scope"]):
        runtime.control_flow(env["owner"], env["workflow"], "cancel")
        _, flow = catalog.register_flow(
            env["admin"],
            {
                "code": "shared-" + uuid4().hex[:8],
                "name": "多角色共享统计",
                "definition": definition,
            },
        )
        env["workflow"] = runtime.start_flow(env["owner"], flow, body)
    assert prepare(env) is False
    with project_scope(env["scope"]):
        output = finish_task(env, ComputeTask.objects.get().pk, "A")
    assert prepare(env) is False
    with project_scope(env["scope"]):
        record = ComputeImport.objects.get(output=output)
        with task_scope(output.task):
            process_import(record)
    assert prepare(env) is True
    workflow = env["workflow"]
    assert workflow.plan["inputs"]["source"] == workflow.plan["inputs"]["context"]
    assert workflow.operator_steps == 1
    with project_scope(env["scope"]):
        assert ComputeTask.objects.count() == 1
        assert ComputeImport.objects.count() == 1


def test_domain_neutral_adapters_are_shared_without_crossing_project_scope(adapted):
    from apps.business_flows.input_adapters import capabilities
    from apps.compute.models import AlgorithmResource, AlgorithmVersion
    from apps.projects.context import ProjectScope

    env = adapted
    env["project"].code = "02"
    env["project"].save(update_fields=["code"])
    with project_scope(
        ProjectScope(
            (env["other_project"].pk,), env["other_project"].pk, env["admin"].pk, True
        )
    ):
        foreign = AlgorithmResource.objects.create(
            project_tag_id=env["other_project"].pk,
            identifier="other-input-adapter",
            name="另一项目转换器",
            created_by=env["admin"],
        )
        other = AlgorithmVersion.objects.create(
            algorithm=foreign,
            version="1.0.0",
            status="published",
            manifest=env["version"].manifest,
            checksum="c" * 64,
        )
    with project_scope(env["scope"]):
        found = {version.pk for version in capabilities(env["owner"])}
        assert env["version"].pk in found
        assert other.pk not in found
    with project_scope(ProjectScope((1,), 1, env["admin"].pk, True)):
        env["version"].algorithm.enabled = False
        env["version"].algorithm.save(update_fields=["enabled"])
    with project_scope(env["scope"]):
        assert env["version"].pk not in {
            version.pk for version in capabilities(env["owner"])
        }
