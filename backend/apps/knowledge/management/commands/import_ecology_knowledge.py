"""Import reviewed ecological claims and optional safe source summaries."""

import hashlib
import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import URLValidator
from django.db import transaction

from apps.audit.service import log_operation
from apps.knowledge.library import retry_document, upload_document
from apps.knowledge.models import KnowledgeDocument, KnowledgeEntry, KnowledgeRevision
from apps.knowledge.services import can_edit, require_project, serialize, validate_entry
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import Project


def identity(data):
    return (
        data["domain"],
        data["subject"].casefold(),
        data["predicate"].casefold(),
        tuple(sorted(set(data["conditions"]))),
    )


def read_bundle(path):
    if not path.is_file() or path.stat().st_size > 3_000_000:
        raise CommandError("知识包须为不超过3 MB的JSON文件")
    try:
        bundle = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise CommandError("无法读取知识包JSON") from exc
    if (
        not isinstance(bundle, dict)
        or bundle.get("schemaVersion") != 1
        or not isinstance(bundle.get("batch"), str)
        or not 1 <= len(bundle["batch"]) <= 100
        or not isinstance(bundle.get("projectCode"), str)
        or not isinstance(bundle.get("entries"), list)
        or not 1 <= len(bundle["entries"]) <= 100
    ):
        raise CommandError(
            "知识包需有schemaVersion=1、batch、projectCode及1–100个entries"
        )
    review = bundle.get("review", {})
    if not isinstance(review, dict) or any(
        not isinstance(review.get(key), str) or not review[key].strip()
        for key in ("collectorCheck", "independentReview", "publicationDecision")
    ):
        raise CommandError("须分别记录收集核对、独立复核和本次发布决定")
    prepared, keys, identities = [], set(), set()
    for item in bundle["entries"]:
        if not isinstance(item, dict):
            raise CommandError("知识条目须为对象")
        key = item.get("seedKey")
        if not isinstance(key, str) or not 1 <= len(key) <= 100 or key in keys:
            raise CommandError("seedKey须为不重复的1–100字符标识")
        try:
            data = validate_entry({k: v for k, v in item.items() if k != "seedKey"})
        except ValidationError as exc:
            raise CommandError(f"{key}：{'；'.join(exc.messages)}") from exc
        if (
            data["domain"] != "arid_ecology"
            or data["status"] != "published"
            or data["rule_kind"] != "none"
            or not data["conditions"]
            or not data["exceptions"]
        ):
            raise CommandError(
                "生态资料须经审阅发布，列明条件/例外，不能直接发布可执行阈值"
            )
        claim = identity(data)
        if claim in identities:
            raise CommandError("同批次同对象、断言及适用条件的条目须先合并")
        keys.add(key)
        identities.add(claim)
        prepared.append((key, data))
    documents = []
    document_rows = bundle.get("documents", [])
    if not isinstance(document_rows, list) or len(document_rows) > 30:
        raise CommandError("来源文档须为最多30项的列表")
    for item in document_rows:
        if not isinstance(item, dict) or item.get("reviewStatus") != "reviewed_summary":
            raise CommandError("默认资料索引只接受经审核的精简来源文档")
        filename = item.get("file")
        if not isinstance(filename, str):
            raise CommandError("资料文件路径无效")
        source = (path.parent / filename).resolve()
        if not source.is_relative_to(path.parent.resolve()) or not source.is_file():
            raise CommandError("来源文档须位于知识包目录内")
        if source.suffix.lower() != ".md" or source.stat().st_size > 1_000_000:
            raise CommandError("审核来源文档须为不超过1 MB的Markdown")
        if hashlib.sha256(source.read_bytes()).hexdigest() != item.get("sha256"):
            raise CommandError("来源文档摘要不匹配，须重新审核后生成知识包")
        if not isinstance(item.get("title"), str) or not 1 <= len(item["title"]) <= 180:
            raise CommandError("来源文档标题无效")
        url = item.get("sourceUrl", "")
        if not isinstance(url, str) or len(url) > 2000:
            raise CommandError("来源文档地址无效")
        try:
            if url:
                URLValidator(schemes=("http", "https"))(url)
            source.read_text(encoding="utf-8-sig")
        except (ValidationError, UnicodeError, OSError) as exc:
            raise CommandError("来源文档地址或文字编码无效") from exc
        documents.append((item, source))
    return bundle, prepared, documents


def merge_sources(entry, data):
    sources = list(data["sources"])
    changed = entry.statement != data["statement"] or entry.object != data["object"]
    for source in entry.sources:
        if source in sources:
            continue
        if changed and not source["title"].startswith("历史修订来源："):
            source = {
                **source,
                "title": ("历史修订来源：" + source["title"])[:300],
                "locator": (f"修订{entry.revision}；" + source.get("locator", ""))[
                    :500
                ],
            }
        if source not in sources:
            sources.append(source)
    if len(sources) > 20:
        raise CommandError("合并来源超过平台上限，请先整理来源")
    return sources


class Command(BaseCommand):
    help = "预演或幂等导入已审阅生态资料；原始材料与争议数值留在独立归档。"

    def add_arguments(self, parser):
        parser.add_argument("--bundle", required=True)
        parser.add_argument("--project-code", required=True)
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--with-documents", action="store_true")

    def handle(self, *args, **options):
        bundle, prepared, documents = read_bundle(Path(options["bundle"]).resolve())
        project = Project.objects.filter(
            code=options["project_code"], is_active=True
        ).first()
        if project is None or bundle["projectCode"] != project.code:
            raise CommandError("知识包与实际启用的目标项目不一致")
        user = (
            get_user_model()
            .objects.filter(pk=options["user_id"], is_active=True)
            .first()
        )
        if user is None:
            raise CommandError("请选择有效知识维护账号")
        result = {
            "batch": bundle["batch"],
            "projectId": project.pk,
            "projectCode": project.code,
            "review": bundle["review"],
            "dryRun": options["dry_run"],
            "created": 0,
            "updated": 0,
            "preserved": 0,
            "entries": [],
            "documents": [],
        }
        scope = ProjectScope((project.pk,), project.pk, user_id=user.pk)
        with project_scope(scope):
            try:
                require_project(user)
                if not can_edit(user):
                    raise CommandError("账号缺少知识维护权限")
            except PermissionDenied as exc:
                raise CommandError(str(exc)) from exc
            with transaction.atomic():
                self._entries(user, project.pk, bundle, prepared, options, result)
            # Upstream indexing is outside the business-data transaction. Its
            # persisted failed state remains visible and retryable on the next import.
            if options["with_documents"]:
                for item, source in documents:
                    old = KnowledgeDocument.objects.filter(
                        sha256=item["sha256"],
                        domain="arid_ecology",
                        visibility="project",
                    ).first()
                    if options["dry_run"]:
                        result["documents"].append(
                            {
                                "title": item["title"],
                                "action": "preserved" if old else "create",
                            }
                        )
                        continue
                    if old and old.status in {"failed", "cancelled"}:
                        doc = retry_document(user, old.pk)
                    else:
                        with source.open("rb") as stream:
                            doc = upload_document(
                                user,
                                File(stream, name=source.name),
                                title=item["title"],
                                source_url=item.get("sourceUrl", ""),
                                domain="arid_ecology",
                            )
                    result["documents"].append(
                        {
                            "id": doc.pk,
                            "title": doc.title,
                            "action": "preserved" if old else "created",
                            "status": doc.status,
                            "detail": doc.detail,
                        }
                    )
        self.stdout.write(json.dumps(result, ensure_ascii=False))

    def _entries(self, user, pid, bundle, prepared, options, result):
        existing = list(KnowledgeEntry.objects.select_for_update())
        for key, data in prepared:
            claim = identity(data)
            entry = next((e for e in existing if e.seed_key == key), None)
            if entry and identity(serialize(entry)) != claim:
                raise CommandError(f"{key}适用条件已改变，请为不同条件另设标识")
            if entry is None:
                matches = [
                    e
                    for e in existing
                    if identity(serialize(e)) == claim
                    or (
                        e.domain == data["domain"]
                        and e.title.casefold() == data["title"].casefold()
                        and set(e.conditions) == set(data["conditions"])
                    )
                ]
                if len(matches) > 1:
                    raise CommandError(f"{key}存在多个同条件条目，请先合并")
                entry = matches[0] if matches else None
            effective = dict(data)
            if entry:
                if set(entry.conditions) == set(data["conditions"]):
                    effective["conditions"] = entry.conditions
                effective["sources"] = merge_sources(entry, data)
                effective["aliases"] = list(
                    dict.fromkeys([*data["aliases"], *entry.aliases])
                )
                if len(effective["aliases"]) > 40:
                    raise CommandError("合并别名超过平台上限")
            action = (
                "preserved"
                if entry and all(getattr(entry, k) == v for k, v in effective.items())
                else "updated"
                if entry
                else "created"
            )
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
                        defaults={"project_tag_id": pid, "snapshot": serialize(entry)},
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
                    target_id=entry.pk,
                    target_name=entry.title,
                    message=f"生态审核知识包：{bundle['batch']}；{key}；独立复核：{bundle['review']['independentReview']}",
                )
            result[action] += 1
            result["entries"].append(
                {"seedKey": key, "id": entry.pk if entry else None, "action": action}
            )
