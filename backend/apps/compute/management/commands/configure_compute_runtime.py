import sys

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from apps.core.config import load_runtime_config_document, write_runtime_config_document


class Command(BaseCommand):
    help = "Configure the compute executor (Docker or native Python process)"

    def add_arguments(self, parser):
        parser.add_argument("--wsl", default="")
        parser.add_argument("--native", action="store_true")

    def handle(self, *args, **options):
        raw = load_runtime_config_document(settings.PROJECT_CONFIG)
        if options["native"] and options["wsl"]:
            raise CommandError("--native 与 --wsl 不能同时使用")
        raw["compute"] = {
            "mode": "native" if options["native"] else "docker",
            "interpreter": sys.executable if options["native"] else "",
            "command": [
                "wsl.exe",
                "--distribution",
                options["wsl"],
                "--user",
                "root",
                "--",
                "docker",
            ]
            if options["wsl"]
            else ["docker"],
            "image": "geomanager-compute:1",
            "memory_mb": 2048,
            "timeout_seconds": 1800,
            "input_mb": 1024,
            "output_mb": 1024,
            "retention_days": 7,
            "user_queue": 3,
            "global_queue": 20,
        }
        write_runtime_config_document(settings.PROJECT_CONFIG, raw)
        self.stdout.write("Compute runtime configuration saved.")
