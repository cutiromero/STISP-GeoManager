"""Import an explicitly scoped, reviewed external geological knowledge bundle."""

import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.service import log_operation
from apps.knowledge.models import KnowledgeEntry, KnowledgeRevision
from apps.knowledge.services import can_edit, require_project, serialize, validate_entry
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import Project


def scope_identity(data: dict) -> tuple:
    """Conditions define the region, evidence type and applicable interpretation."""
    return (
        data["domain"],
        data["subject"].casefold(),
        data["predicate"].casefold(),
        tuple(sorted(set(data["conditions"]))),
    )


def read_bundle(path: Path) -> tuple[str, list[tuple[str, dict]]]:
    if not path.is_file() or path.stat().st_size > 3_000_000:
        raise CommandError("知识包须为不超过 3 MB 的 JSON 文件")
    try:
        bundle = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeError, OSError) as exc:
        raise CommandError("无法读取知识包 JSON") from exc
    if (
        not isinstance(bundle, dict)
        or bundle.get("schemaVersion") != 1
        or not isinstance(bundle.get("batch"), str)
        or not 1 <= len(bundle["batch"]) <= 100
        or not isinstance(bundle.get("entries"), list)
        or not 1 <= len(bundle["entries"]) <= 300
    ):
        raise CommandError("知识包需有 schemaVersion=1、batch 及 1–300 个 entries")
    prepared, keys, identities = [], set(), set()
    for item in bundle["entries"]:
        if not isinstance(item, dict):
            raise CommandError("知识条目须为对象")
        key = item.get("seedKey")
        if not isinstance(key, str) or not 1 <= len(key) <= 100 or key in keys:
            raise CommandError("seedKey 须为不重复的 1–100 字符标识")
        try:
            data = validate_entry({k: v for k, v in item.items() if k != "seedKey"})
        except ValidationError as exc:
            raise CommandError(f"{key}：{'；'.join(exc.messages)}") from exc
        if (
            data["domain"] != "geology"
            or data["status"] != "published"
            or not data["conditions"]
            or not data["exceptions"]
        ):
            raise CommandError("地质知识须已审阅发布，并列出适用条件及必要例外")
        identity = scope_identity(data)
        if identity in identities:
            raise CommandError("同批次同对象、同断言及同适用条件的条目须先合并")
        keys.add(key)
        identities.add(identity)
        prepared.append((key, data))
    return bundle["batch"], prepared


def merged_lists(old: list, new: list, maximum: int) -> list:
    values = list(new)
    for item in old:
        if item not in values:
            values.append(item)
    if len(values) > maximum:
        raise CommandError("合并后来源或别名超过平台上限，请整理知识包再导入")
    return values


def merged_sources(entry: KnowledgeEntry, data: dict) -> list:
    old = entry.sources
    if entry.statement != data["statement"] or entry.object != data["object"]:
        old = [
            {
                **source,
                "title": ("历史修订来源（旧断言）：" + source["title"])[:300],
                "locator": (f"修订{entry.revision}；" + source.get("locator", ""))[
                    :500
                ],
            }
            if source not in data["sources"]
            and not source["title"].startswith("历史修订来源（旧断言）：")
            else source
            for source in old
        ]
    return merged_lists(old, data["sources"], 20)


class Command(BaseCommand):
    help = "导入已审阅地质材料；同适用条件的新依据生效，旧版快照可追溯。"

    def add_arguments(self, parser):
        parser.add_argument("--bundle", required=True)
        parser.add_argument("--project-id", type=int, required=True)
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        batch, prepared = read_bundle(Path(options["bundle"]))
        pid = options["project_id"]
        if not Project.objects.filter(pk=pid, is_active=True).exists():
            raise CommandError("请选择实际存在且启用的目标项目")
        user = (
            get_user_model()
            .objects.filter(pk=options["user_id"], is_active=True)
            .first()
        )
        if user is None:
            raise CommandError("请选择有效的知识维护账号")
        scope = ProjectScope((pid,), pid, user_id=user.pk, superadmin=user.is_superuser)
        result = {
            "batch": batch,
            "projectId": pid,
            "dryRun": options["dry_run"],
            "created": 0,
            "updated": 0,
            "preserved": 0,
            "scopeOverlaps": [],
            "entries": [],
        }
        with project_scope(scope), transaction.atomic():
            try:
                require_project(user)
                if not can_edit(user):
                    raise CommandError("账号缺少知识维护权限")
            except PermissionDenied as exc:
                raise CommandError(str(exc)) from exc
            existing = list(KnowledgeEntry.objects.select_for_update())
            by_key = {entry.seed_key: entry for entry in existing if entry.seed_key}
            by_identity = {}
            for entry in existing:
                by_identity.setdefault(scope_identity(serialize(entry)), []).append(
                    entry
                )
            for key, data in prepared:
                identity = scope_identity(data)
                entry = by_key.get(key)
                if entry is not None and scope_identity(serialize(entry)) != identity:
                    raise CommandError(f"{key} 的适用条件已改变，请为不同条件另设标识")
                matches = by_identity.get(identity, [])
                if entry is None:
                    if len(matches) > 1:
                        raise CommandError(f"{key} 存在多个同条件旧条目，请先人工合并")
                    entry = matches[0] if matches else None
                overlaps = [
                    old.id
                    for old in existing
                    if old.subject.casefold() == data["subject"].casefold()
                    and old.predicate.casefold() == data["predicate"].casefold()
                    and scope_identity(serialize(old)) != identity
                ]
                if overlaps:
                    result["scopeOverlaps"].append(
                        {"seedKey": key, "entryIds": overlaps}
                    )
                effective = dict(data)
                if entry is not None:
                    effective["sources"] = merged_sources(entry, data)
                    effective["aliases"] = merged_lists(
                        entry.aliases, data["aliases"], 40
                    )
                    unchanged = all(
                        getattr(entry, field) == value
                        for field, value in effective.items()
                    )
                    action = "preserved" if unchanged else "updated"
                else:
                    action = "created"
                result[action] += 1
                row = {
                    "seedKey": key,
                    "action": action,
                    "id": entry.id if entry else None,
                }
                if not options["dry_run"] and action != "preserved":
                    if entry is None:
                        entry = KnowledgeEntry.objects.create(
                            seed_key=key, updated_by=user, **effective
                        )
                        existing.append(entry)
                    else:
                        KnowledgeRevision.objects.get_or_create(
                            entry=entry,
                            revision=entry.revision,
                            defaults={
                                "project_tag_id": pid,
                                "snapshot": serialize(entry),
                            },
                        )
                        for field, value in effective.items():
                            setattr(entry, field, value)
                        entry.revision += 1
                        entry.updated_by = user
                        if not entry.seed_key:
                            entry.seed_key = key
                        entry.save()
                    KnowledgeRevision.objects.create(
                        project_tag_id=pid,
                        entry=entry,
                        revision=entry.revision,
                        snapshot=serialize(entry),
                    )
                    log_operation(
                        user,
                        "knowledge",
                        "import" if action == "created" else "update",
                        "success",
                        target_type="knowledge_entry",
                        target_id=entry.id,
                        target_name=entry.title,
                        message=f"地质材料知识包：{batch}；条目标识：{key}",
                    )
                    by_key[key] = entry
                    by_identity[identity] = [entry]
                    row["id"] = entry.id
                result["entries"].append(row)
        self.stdout.write(json.dumps(result, ensure_ascii=False))
