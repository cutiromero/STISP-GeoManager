"""Register explicit independent evaluation without changing workflow inputs."""

import json
from pathlib import Path

from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError

from apps.agent.models import AgentWorkflow
from apps.agent.workflow import authorize_workflow_history
from apps.agent.workflow_reports import authorize_context
from apps.agent.workflow_validation import publish_validation
from apps.compute.packages import ComputeError
from apps.projects.context import ProjectScope, project_scope


class Command(BaseCommand):
    help = "登记工作流独立评价摘要和文件；只保存到业务根目录，已有不同内容拒绝覆盖"

    def add_arguments(self, parser):
        parser.add_argument("--workflow-id", required=True)
        parser.add_argument(
            "--summary", required=True, help="UTF-8 JSON，包含 scope、summary、sections"
        )
        parser.add_argument(
            "--file",
            action="append",
            default=[],
            help="可重复：受控文件键=本地文件路径",
        )

    def handle(self, *args, **options):
        try:
            workflow = AgentWorkflow.objects.select_related("project_tag").get(
                pk=options["workflow_id"]
            )
            summary = json.loads(
                Path(options["summary"]).read_text(encoding="utf-8-sig")
            )
            files = {}
            for item in options["file"]:
                key, separator, path = item.partition("=")
                if not separator or not path or key in files:
                    raise CommandError("--file 应为不重复的 key=本地路径")
                files[key] = Path(path)
            scope = ProjectScope(
                (workflow.project_tag_id,), workflow.project_tag_id, workflow.owner_id
            )
            with project_scope(scope):
                user, policy = authorize_workflow_history(workflow)
                authorize_context(workflow, user, policy, history=True)
                manifest = publish_validation(workflow, summary, files)
            self.stdout.write(
                json.dumps(
                    {
                        "workflowId": str(workflow.id),
                        "registered": True,
                        "fileCount": len(manifest["files"]),
                    },
                    ensure_ascii=False,
                )
            )
        except (
            AgentWorkflow.DoesNotExist,
            OSError,
            ValueError,
            ComputeError,
            PermissionDenied,
        ) as exc:
            raise CommandError("独立评价登记失败：" + str(exc)) from exc
