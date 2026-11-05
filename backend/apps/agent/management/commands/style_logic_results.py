from contextlib import nullcontext

from django.core.management.base import BaseCommand, CommandError
from django.test.utils import override_settings

from apps.agent.geology_generic import MULTI_FAMILY
from apps.agent.models import AgentWorkflow
from apps.agent.result_colors import style_result
from apps.agent.tools import resolve_resource
from apps.agent.workflow import authorize_workflow_history
from apps.projects.context import ProjectScope, project_scope


class Command(BaseCommand):
    help = "为指定逻辑推理工作流已有矢量成果补齐配色建议；默认仅统计，--apply 才写入。"

    def add_arguments(self, parser):
        parser.add_argument("--workflow", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--no-model", action="store_true")

    def handle(self, *args, **options):
        workflow = AgentWorkflow.objects.filter(
            pk=options["workflow"], workflow_type__in=MULTI_FAMILY
        ).first()
        if not workflow:
            raise CommandError("未找到指定逻辑推理工作流")
        outputs = {
            output["resourceId"]: output["key"]
            for stage in workflow.plan.get("stages", [])
            for output in stage.get("outputs", [])
            if output.get("kind") == "vector" and output.get("resourceId")
        }
        scope = ProjectScope(
            (workflow.project_tag_id,), workflow.project_tag_id, workflow.owner_id
        )
        model_settings = (
            override_settings(AGENT_COLOR_SUGGESTIONS_ENABLED=False)
            if options["no_model"]
            else nullcontext()
        )
        with project_scope(scope), model_settings:
            user, policy = authorize_workflow_history(workflow)
            resources = [
                (resolve_resource(user, policy, identifier), key)
                for identifier, key in outputs.items()
            ]
            if options["apply"]:
                for resource, key in resources:
                    style_result(workflow, resource, key)
        self.stdout.write(
            f"{'已处理' if options['apply'] else '待处理'} {len(outputs)} 项矢量成果；科研数据与计算几何不变。"
        )
