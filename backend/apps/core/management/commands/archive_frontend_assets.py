from pathlib import Path
import json
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from apps.core.frontend_assets import archive_assets


class Command(BaseCommand):
    help = "Retain a published public frontend build for existing browser tabs"

    def add_arguments(self, parser):
        parser.add_argument("--source", type=Path, default=None)

    def handle(self, *args, **options):
        try:
            result = archive_assets(options["source"] or settings.FRONTEND_DIST)
        except (OSError, ValueError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(json.dumps(result))
