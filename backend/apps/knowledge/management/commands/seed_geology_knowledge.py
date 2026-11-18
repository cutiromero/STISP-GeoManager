import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import Project
from apps.knowledge.models import KnowledgeEntry, KnowledgeRevision
from apps.knowledge.services import serialize, validate_entry


BATCH_FILES = {
    "base": "seed_entries.json",
    "geology-20261009": "seed_entries_20261009.json",
    "knowledge-zones-20261010": "seed_entries_20261010.json",
}
PROJECT_BY_DOMAIN = {
    "remote_sensing": "default",
    "pipelines": "gd",
    "geology": "02",
    "arid_ecology": "demo-arid-ecology",
}


class Command(BaseCommand):
    help = "按项目载入地学知识种子，保留条目编号、来源和人工修订。"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--reassign-existing",
            action="store_true",
            help="只调整该批次历史公开条目的所属项目，不导入缺失条目。",
        )
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
        entries = KnowledgeEntry._base_manager
        revisions = KnowledgeRevision._base_manager
        moved = created = preserved = 0
        with transaction.atomic():
            codes = {PROJECT_BY_DOMAIN[data["domain"]] for _, data in validated}
            projects = dict(
                Project.objects.filter(
                    code__in=codes, is_active=True, deleted_at__isnull=True
                ).values_list("code", "pk")
            )
            if missing := codes - projects.keys():
                raise CommandError(f"缺少启用的目标项目：{', '.join(sorted(missing))}")
            for key, data in validated:
                pid = projects[PROJECT_BY_DOMAIN[data["domain"]]]
                existing = entries.filter(project_tag_id=pid, seed_key=key).first()
                legacy = (
                    entries.filter(project_tag_id=1, seed_key=key).first()
                    if pid != 1
                    else None
                )
                if existing and legacy:
                    raise CommandError(
                        f"种子 {key} 在公开和目标项目均已存在，需先处理冲突"
                    )
                if existing:
                    preserved += 1
                    continue
                if legacy:
                    moved += 1
                    if not options["dry_run"]:
                        entries.filter(pk=legacy.pk, project_tag_id=1).update(
                            project_tag_id=pid
                        )
                        for version in revisions.filter(entry_id=legacy.pk):
                            # Preserve revision identity and content; only its scope changes.
                            revisions.filter(pk=version.pk).update(
                                project_tag_id=pid,
                                snapshot={**version.snapshot, "projectTagId": pid},
                            )
                    continue
                if options["reassign_existing"]:
                    continue
                created += 1
                if not options["dry_run"]:
                    with project_scope(ProjectScope((pid,), pid, superadmin=True)):
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
                    "preserved": preserved,
                    "moved": moved,
                }
            )
        )
