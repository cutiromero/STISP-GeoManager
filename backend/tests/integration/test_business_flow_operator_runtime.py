"""Real compute admission and CSV outputs across AI and human operator revisions."""

from copy import deepcopy
from uuid import uuid4

from django.contrib.auth.models import Permission
from django.utils import timezone
import pytest

from apps.agent.models import AgentPolicy, AgentRuntime
from apps.agent.policy import default_policy
from apps.business_flows import catalog, engine, runtime
from apps.business_flows.builtins import source_summary_definition
from apps.business_flows.state import state
from apps.compute.data import inspect_output
from apps.compute.models import ComputeOutput, ComputeTask
from apps.compute.packages import checksum
from apps.core.storage import app_path
from apps.projects.context import ProjectScope, project_scope
from tests.integration.test_compute import setup_compute  # noqa: F401

# ruff: noqa: F811


@pytest.fixture
def operators(setup_compute, settings):
    env = setup_compute
    settings.AGENT_MODELS = [
        {
            "alias": "mock",
            "name": "Mock",
            "model_id": "mock-local",
            "base_url": "http://127.0.0.1:19100/v1",
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
    AgentPolicy.objects.update_or_create(pk=1, defaults={"value": policy})
    AgentRuntime.objects.update_or_create(
        name="worker", defaults={"heartbeat": timezone.now()}
    )
    scope = ProjectScope((env["project"].pk,), env["project"].pk, env["owner"].pk)

    def create(*, ai=True, human=False, revisions=2):
        definition = source_summary_definition()
        definition["nodes"][0] = {
            "id": "calculate",
            "kind": "operator",
            "title": "统计实际资料",
            "description": "核查当前统计结果",
            "dependsOn": [],
            "dataRoles": ["source"],
            "instruction": "按实际字段汇总，不修改原始资料。",
            "algorithmVersionId": env["version"].pk,
            "parameters": deepcopy(env["body"]["parameters"]),
            "review": {"ai": ai, "human": human, "maxRevisions": revisions},
        }
        definition["nodes"][1]["dependsOn"] = ["calculate"]
        with project_scope(scope):
            _, version = catalog.register_flow(
                env["admin"],
                {
                    "code": "operator-" + uuid4().hex[:8],
                    "name": "统计业务流",
                    "definition": definition,
                },
            )
            workflow = runtime.start_flow(
                env["owner"],
                version,
                {
                    "model": "mock",
                    "inputs": {"source": env["resource"].pk},
                    "goal": "汇总实际数据",
                    "idempotencyKey": uuid4().hex,
                },
            )
        return workflow

    return {**env, "scope": scope, "create": create}


def finish_task(env, task_id, label):
    with project_scope(env["scope"]):
        task = ComputeTask.objects.get(pk=task_id)
        task.status = "succeeded"
        task.save(update_fields=["status"])
        declared = next(
            row for row in task.version.manifest["outputs"] if row["kind"] == "table"
        )
        path = app_path(
            "projects",
            str(task.project_tag_id),
            "compute",
            "outputs",
            str(task.pk),
            declared["file"],
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"region,value\n{label},6\n", encoding="utf-8")
        return ComputeOutput.objects.create(
            task=task,
            key=declared["key"],
            label=declared["label"],
            kind="table",
            file_name=declared["file"],
            path=path.relative_to(app_path()).as_posix(),
            size_bytes=path.stat().st_size,
            checksum=checksum(path),
            metadata=inspect_output(path, "table"),
        )


def advance(env, workflow):
    engine.advance(workflow.pk)
    workflow.refresh_from_db()
    with project_scope(env["scope"]):
        return runtime.serialize_run(env["owner"], workflow)


def review_stub(calls, reject_until):
    def review(workflow, node, attempt, evidence, **callbacks):
        calls.append({"attempt": attempt, "evidence": deepcopy(evidence)})
        if attempt <= reject_until:
            return {
                "decision": "request_changes",
                "reason": "请按实际统计调整汇总方法",
                "repairInstructions": "在登记参数范围内调整汇总方法",
                "issues": [
                    {
                        "code": "method",
                        "message": "当前方法未满足节点要求",
                        "evidenceIds": [evidence[0]["id"]],
                    }
                ],
                "evidenceIds": [evidence[0]["id"]],
                "humanApprovalRequired": node["review"]["human"],
                "audit": {},
            }
        return {
            "decision": "accept",
            "reason": "已核查本轮实际输出",
            "repairInstructions": "",
            "issues": [],
            "evidenceIds": [row["id"] for row in evidence],
            "humanApprovalRequired": node["review"]["human"],
            "audit": {},
        }

    return review


def planner_stub(calls):
    def propose(
        workflow,
        node,
        attempt,
        evidence,
        manifest,
        current_parameters,
        feedback,
        **callbacks,
    ):
        calls.append(
            {
                "attempt": attempt,
                "evidence": deepcopy(evidence),
                "before": deepcopy(current_parameters),
                "feedback": deepcopy(feedback),
            }
        )
        parameters = {
            **current_parameters,
            "method": "sum" if current_parameters["method"] == "mean" else "max",
        }
        return {
            "canRepair": True,
            "parameters": parameters,
            "reason": "按反馈修订已声明汇总方法",
            "evidenceIds": [row["id"] for row in evidence],
            "audit": {},
        }

    return propose


def test_ai_operator_revisions_submit_new_real_tasks_and_carry_actual_results(
    operators, monkeypatch
):
    env = operators
    reviews = []
    plans = []
    monkeypatch.setattr(
        "apps.agent.business_flow_review.review_node", review_stub(reviews, 2)
    )
    monkeypatch.setattr(
        "apps.agent.business_flow_operator_repair.propose_parameters",
        planner_stub(plans),
    )
    workflow = env["create"]()
    advance(env, workflow)
    assert workflow.status == "waiting_compute", workflow.detail
    first_task = state(workflow)["nodes"]["calculate"]["computeTaskId"]
    old_output = finish_task(env, first_task, "OLD_REJECTED")
    advance(env, workflow)
    assert workflow.status == "queued", workflow.detail
    advance(env, workflow)
    assert workflow.status == "waiting_compute", workflow.detail
    second_task = state(workflow)["nodes"]["calculate"]["computeTaskId"]
    assert second_task != first_task
    assert plans[0]["before"]["method"] == "mean"
    assert any(row["id"] == f"output-{old_output.pk}" for row in plans[0]["evidence"])
    with project_scope(env["scope"]):
        assert ComputeTask.objects.get(pk=second_task).parameters["method"] == "sum"
    middle_output = finish_task(env, second_task, "REVISE_AGAIN")
    advance(env, workflow)
    advance(env, workflow)
    assert workflow.status == "waiting_compute", workflow.detail
    third_task = state(workflow)["nodes"]["calculate"]["computeTaskId"]
    assert third_task not in {first_task, second_task}
    assert plans[1]["before"]["method"] == "sum"
    assert any(
        row["id"] == f"output-{middle_output.pk}" for row in plans[1]["evidence"]
    )
    final_output = finish_task(env, third_task, "ACCEPTED_FINAL")
    result = advance(env, workflow)
    assert result["nodes"][0]["status"] == "succeeded", workflow.detail
    advance(env, workflow)
    result = advance(env, workflow)
    assert workflow.status == "succeeded", workflow.detail
    assert result["resultOutputIds"] == [final_output.pk]
    with project_scope(env["scope"]):
        assert (
            ComputeTask.objects.filter(
                pk__in=[first_task, second_task, third_task]
            ).count()
            == 3
        )
        assert (
            ComputeOutput.objects.filter(
                pk__in=[old_output.pk, middle_output.pk, final_output.pk]
            ).count()
            == 3
        )


def test_human_operator_return_plans_and_submits_a_new_calculation(
    operators, monkeypatch
):
    env = operators
    plans = []
    monkeypatch.setattr(
        "apps.agent.business_flow_operator_repair.propose_parameters",
        planner_stub(plans),
    )
    workflow = env["create"](ai=False, human=True, revisions=1)
    advance(env, workflow)
    assert workflow.status == "waiting_compute", workflow.detail
    old_id = state(workflow)["nodes"]["calculate"]["computeTaskId"]
    old_output = finish_task(env, old_id, "HUMAN_RETURNED")
    result = advance(env, workflow)
    assert workflow.status == "waiting_approval", workflow.detail
    with project_scope(env["scope"]):
        runtime.decide_flow(
            env["owner"],
            workflow,
            {
                "nodeId": "calculate",
                "decision": "request_changes",
                "feedback": "请改用求和核查",
                "revision": result["revision"],
                "idempotencyKey": uuid4().hex,
            },
        )
    advance(env, workflow)
    assert workflow.status == "waiting_compute", workflow.detail
    assert len(plans) == 1
    assert any(row["id"] == f"output-{old_output.pk}" for row in plans[0]["evidence"])
    new_id = state(workflow)["nodes"]["calculate"]["computeTaskId"]
    assert new_id != old_id
    with project_scope(env["scope"]):
        assert ComputeTask.objects.get(pk=new_id).parameters["method"] == "sum"


def test_operator_without_parameter_repair_does_not_resubmit_same_task(
    operators, monkeypatch
):
    env = operators
    reviews = []
    plans = []
    monkeypatch.setattr(
        "apps.agent.business_flow_review.review_node", review_stub(reviews, 1)
    )

    def no_repair(*args, **kwargs):
        plans.append(True)
        return {
            "canRepair": False,
            "parameters": {},
            "reason": "当前已声明参数无法解决反馈问题",
            "evidenceIds": [],
            "audit": {},
        }

    monkeypatch.setattr(
        "apps.agent.business_flow_operator_repair.propose_parameters", no_repair
    )
    workflow = env["create"]()
    advance(env, workflow)
    assert workflow.status == "waiting_compute", workflow.detail
    original = state(workflow)["nodes"]["calculate"]["computeTaskId"]
    finish_task(env, original, "REJECTED")
    advance(env, workflow)
    advance(env, workflow)
    assert workflow.status == "waiting_approval" and len(plans) == 1
    assert (
        state(workflow)["nodes"]["calculate"]["contextRecovery"]["kind"]
        == "execution_error"
    )
    with project_scope(env["scope"]):
        assert ComputeTask.objects.count() == 1
