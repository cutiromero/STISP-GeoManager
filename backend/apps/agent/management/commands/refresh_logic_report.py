"""Create an audited model interpretation revision, preserving prior reports."""

from copy import deepcopy
import json
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.agent.models import AgentWorkflow
from apps.agent.demo_decisions import decide
from apps.agent.demo_results import read_results
from apps.agent.demo_workflow import authorize_demo
from apps.agent.model_guard import ModelStreamGuard
from apps.agent.model_activity import WorkflowModelActivity
from apps.agent.config import registry
from apps.agent.workflow import _authorize, _state_hash, step
from apps.agent.workflow_reports import _paths, generate_report
from apps.compute.packages import checksum_scope
from apps.projects.context import ProjectScope, project_scope


class Command(BaseCommand):
    help = (
        "实际模型重新解读已完成逻辑推理成果，新增报告版本；不重跑算子。须显式 --apply。"
    )

    def add_arguments(self, parser):
        parser.add_argument("--workflow", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if not options["apply"]:
            raise CommandError("新增报告解读需要 --apply；科学成果和原报告保留")
        workflow = AgentWorkflow._base_manager.get(pk=options["workflow"])
        if (
            workflow.workflow_type
            not in {"geology_generic", "geology_multi_element_reasoning"}
            or workflow.status != "succeeded"
        ):
            raise CommandError("仅可解读已完成的综合地质任务")
        scope = ProjectScope(
            (workflow.project_tag_id,), workflow.project_tag_id, workflow.owner_id
        )
        with project_scope(scope), checksum_scope():
            self.refresh(workflow)

    def refresh(self, workflow):
        expected = workflow.plan_hash
        if len(workflow.plan.get("reportInterpretationHistory", [])) >= 6:
            raise CommandError("已保留6版报告解读，请另建任务继续分析")
        user, policy = _authorize(workflow)
        policy = {
            **policy,
            "_thinking": False,
            "reasoningEffort": "low",
            "maxOutputTokens": min(policy["maxOutputTokens"], 6144),
        }
        original_report = _paths(workflow)[2]
        prior = deepcopy(workflow.plan.get("finalDecision"))
        stage = {
            "name": "final_analysis",
            "identifier": "finish",
            "bindings": {},
            "parameters": {},
            "status": "pending",
            "outputs": [],
        }
        results = []
        for item in workflow.plan["stages"]:
            if item.get("taskId"):
                results.extend(read_results(workflow, user, policy, item["taskId"]))
        calls = set()

        def authorize():
            current = AgentWorkflow.objects.get(pk=workflow.pk)
            if current.status != "succeeded" or current.plan_hash != expected:
                raise CommandError("任务已变化，未更新报告")
            actor, current_policy = _authorize(current)
            authorize_demo(current, actor, current_policy, history=True)

        guard = ModelStreamGuard(
            authorize, time.monotonic() + min(policy["maxRunSeconds"], 120)
        )
        activity = WorkflowModelActivity(
            workflow, "更新报告分析", registry()[workflow.model], policy, guard
        )

        def record(attempt):
            if attempt["status"] == "requesting":
                identity = (attempt["attempt"], attempt["requestSha256"])
                if (
                    identity not in calls
                    and workflow.plan.get("actualModelCallCount", 0) + len(calls)
                    >= workflow.max_iterations
                ):
                    raise CommandError("剩余模型请求额度不足，原报告保留")
                calls.add(identity)

        guard.poll()
        try:
            decision, edits = decide(
                workflow,
                user,
                policy,
                stage,
                results,
                guard,
                record,
                on_thinking=activity.thinking,
                on_progress=activity.progress,
            )
            if edits or any(
                word in json.dumps(decision, ensure_ascii=False)
                for word in ("确定性规则", "非模型逐项审阅")
            ):
                raise CommandError("报告解读未满足表达要求，原报告保留")
            guard.poll()
        except Exception as exc:
            with transaction.atomic():
                from apps.agent.workflow_controls import locked_workflow

                current = locked_workflow(workflow.pk)
                current.plan["actualModelCallCount"] = current.plan.get(
                    "actualModelCallCount", 0
                ) + len(calls)
                current.plan_hash = _state_hash(current.plan)
                current.save(update_fields=["plan", "plan_hash", "updated_at"])
                step(
                    current,
                    "report_reinterpretation",
                    status="failed",
                    message="报告解读未完成，原报告保留",
                    action={"requests": len(calls), "error": str(exc)[:200]},
                )
            raise CommandError(str(exc)) from exc
        with transaction.atomic():
            from apps.agent.workflow_controls import locked_workflow

            current = locked_workflow(workflow.pk)
            if current.status != "succeeded" or current.plan_hash != expected:
                raise CommandError("任务已变化，未更新报告")
            history = current.plan.setdefault("reportInterpretationHistory", [])
            history.append(
                {
                    "revision": current.plan.get("reportInterpretationRevision", 0),
                    "decision": prior,
                    "reportPath": original_report,
                    "planHash": expected,
                }
            )
            current.plan["reportInterpretationRevision"] = len(history)
            current.plan["actualModelCallCount"] = current.plan.get(
                "actualModelCallCount", 0
            ) + len(calls)
            current.plan["finalDecision"] = decision
            current.plan["finalStage"] = {
                **stage,
                "decision": decision,
                "status": "completed",
            }
            current.plan_hash = _state_hash(current.plan)
            current.save(update_fields=["plan", "plan_hash", "updated_at"])
            step(
                current,
                "report_reinterpretation",
                message="大模型已结合实际算子成果更新分析报告，科学计算结果保留",
                action={
                    "model": current.model,
                    "revision": len(history),
                    "requests": len(calls),
                },
                output_refs={"previousReport": original_report},
            )
        report = generate_report(current, user, policy)
        self.stdout.write(
            json.dumps(
                {
                    "workflowId": str(current.pk),
                    "revision": len(history),
                    "modelMode": decision.get("modelMode"),
                    "report": report,
                    "scienceResultsPreserved": True,
                },
                ensure_ascii=False,
            )
        )
