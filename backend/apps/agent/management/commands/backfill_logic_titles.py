from django.core.management.base import BaseCommand

from apps.agent.conversation_titles import DEFAULT_LOGIC_PROMPT, update_logic_title
from apps.agent.models import Conversation
from apps.compute.project_tools import GEOLOGY_PROJECT_CODES


class Command(BaseCommand):
    help = "回填逻辑推理项目的默认历史对话标题；默认仅统计，--apply 才写入。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        conversations = Conversation.objects.filter(
            project_tag__code__in=GEOLOGY_PROJECT_CODES,
            title__startswith=DEFAULT_LOGIC_PROMPT,
        ).order_by("id")
        count = 0
        for conversation in conversations.iterator():
            run = conversation.runs.order_by("created_at", "id").first()
            if run and (
                not options["apply"] or update_logic_title(run, allow_new=False)
            ):
                count += 1
        self.stdout.write(
            f"{'已回填' if options['apply'] else '待回填'} {count} 个对话；自定义标题不变。"
        )
