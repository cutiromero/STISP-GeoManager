import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.projects.context import ProjectScope, project_scope
from apps.knowledge.models import KnowledgeEntry, KnowledgeRevision
from apps.knowledge.services import serialize, validate_entry


BATCH_FILES = {
    "base": "seed_entries.json",
    "geology-20261009": "seed_entries_20261009.json",
    "knowledge-zones-20261010": "seed_entries_20261010.json",
}


class Command(BaseCommand):
    help = "载入带公开来源的地学基础知识；已有条目及人工修订保持不变。"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--batch",
            choices=tuple(BATCH_FILES),
            default="base",
            help="base 保持原有范围；按日期选择对应的知识补充批次。",
        )

    def handle(self, *args, **options):
        batch = options["batch"]
        path = Path(__file__).parents[2] / BATCH_FILES[batch]
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
                    "batch": batch,
                    "dryRun": options["dry_run"],
                    "created": created,
                    "preserved": len(validated) - created,
                }
            )
        )
