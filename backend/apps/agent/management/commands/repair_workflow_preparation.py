"""Restore only a failed preparation's already-frozen rule evidence."""

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.agent.models import AgentWorkflow
from apps.agent.policy import fresh_user, require_access
from apps.agent.workflow import step
from apps.agent.workflow_controls import locked_workflow
from apps.agent.workflow_resources import authorize_workflow_resources
from apps.compute.packages import checksum
from apps.core.storage import table_data_path
from apps.knowledge.trial_rules import SCENARIO, read_bound_rules
from apps.projects.context import ProjectScope, project_scope

# Configuration: a completed plan or any execution must never be rewritten.
ELIGIBLE_TYPES = {"geology_generic", SCENARIO}
ELIGIBLE_STATUSES = {"failed", "interrupted"}


def eligible(workflow):
    if (
        workflow.workflow_type not in ELIGIBLE_TYPES
        or workflow.status not in ELIGIBLE_STATUSES
        or workflow.execute_operators
        or workflow.plan.get("scenarioVersion")
        or workflow.evidence
        or not workflow.plan.get("trialRuleBindings")
        or workflow.steps.exclude(compute_task_id=None).exists()
    ):
        raise CommandError("仅可补齐尚未执行、缺少依据快照的准备失败记录")


class Command(BaseCommand):
    help = (
        "从原冻结规则补齐准备失败记录的依据；不重启任务、不改变预算或批准。默认只校验。"
    )

    def add_arguments(self, parser):
        parser.add_argument("--workflow", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        workflow = AgentWorkflow._base_manager.get(pk=options["workflow"])
        eligible(workflow)
        user = fresh_user(workflow.owner_id)
        with project_scope(
            ProjectScope((workflow.project_tag_id,), workflow.project_tag_id, user.pk)
        ):
            policy = require_access(user, "agent", workflow.model)
            authorize_workflow_resources(user, policy, workflow.resource_ids, workflow)
            entries = read_bound_rules(
                user,
                workflow.project_tag_id,
                SCENARIO,
                [
                    {
                        key: row[key]
                        for key in ("id", "revision", "ruleId", "ruleVersion")
                    }
                    for row in workflow.plan["trialRuleBindings"]
                ],
                expected=workflow.plan["trialRulesDigest"],
                history=True,
            )
            path = table_data_path(f"demo/workflows/{workflow.pk}/trial-rules.csv")
            if checksum(path) != workflow.plan["trialRulesSnapshot"]["frozenChecksum"]:
                raise CommandError("原冻结规则文件与记录不一致，不补齐依据")
            if options["apply"]:
                with transaction.atomic():
                    current = locked_workflow(workflow.pk)
                    eligible(current)
                    if (
                        current.plan != workflow.plan
                        or current.updated_at != workflow.updated_at
                    ):
                        raise CommandError("任务已变化，请重新核对")
                    current.evidence = entries
                    current.save(update_fields=["evidence", "updated_at"])
                    step(
                        current,
                        "preparation_evidence_recovered",
                        message="已从原冻结规则恢复准备期依据快照；原失败状态与批准范围保留",
                        action={
                            "entryIds": [row["id"] for row in entries],
                            "trialRulesDigest": current.plan["trialRulesDigest"],
                            "executionRestarted": False,
                        },
                    )
            self.stdout.write(
                json.dumps(
                    {
                        "workflowId": str(workflow.pk),
                        "applied": options["apply"],
                        "entryIds": [row["id"] for row in entries],
                        "status": workflow.status,
                        "executionRestarted": False,
                    },
                    ensure_ascii=False,
                )
            )
