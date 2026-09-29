import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.projects.context import ProjectScope, project_scope
from apps.knowledge.models import KnowledgeEntry, KnowledgeRevision
from apps.knowledge.services import serialize, validate_entry


class Command(BaseCommand):
    help = "载入带公开来源的地学基础知识；已有条目及人工修订保持不变。"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        path = Path(__file__).parents[2] / "seed_entries.json"
        seeds = json.loads(path.read_text(encoding="utf-8"))
        validated = []
        keys = set()
        for item in seeds:
            key = item["seedKey"]
            if not key or key in keys:
                raise CommandError("知识种子标识为空或重复")
            keys.add(key)
            validated.append(
                (key, validate_entry({k: v for k, v in item.items() if k != "seedKey"}))
            )
        with (
            project_scope(ProjectScope((1,), 1, superadmin=True)),
            transaction.atomic(),
        ):
            created = 0
            for key, data in validated:
                if KnowledgeEntry.objects.filter(seed_key=key).exists():
                    continue
                created += 1
                if not options["dry_run"]:
                    entry = KnowledgeEntry.objects.create(seed_key=key, **data)
                    KnowledgeRevision.objects.create(
                        entry=entry, revision=1, snapshot=serialize(entry)
                    )
        self.stdout.write(
            json.dumps(
                {
                    "dryRun": options["dry_run"],
                    "created": created,
                    "preserved": len(validated) - created,
                }
            )
        )
