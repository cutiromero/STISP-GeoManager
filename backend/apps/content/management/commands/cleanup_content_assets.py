from django.core.management.base import BaseCommand
from apps.content.views import cleanup_pending_assets


class Command(BaseCommand):
    help = "清理超过 24 小时仍未提交的内容附件"

    def handle(self, *args, **options):
        self.stdout.write(f"已清理 {cleanup_pending_assets()} 个过期附件")
