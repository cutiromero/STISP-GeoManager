"""Project-aware, source-grounded retrieval; no external index is implied."""

import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import URLValidator
from django.db.models import Q

from apps.projects.context import is_superadmin, selected_project_id
from apps.projects.models import Project, ProjectMembership
from .models import KnowledgeEntry
from .domains import domain_options, search_terms, validate_domain, validate_domains

TEXT_FIELDS = {
    "title": 180,
    "category": 80,
    "subject": 120,
    "predicate": 120,
    "object": 120,
    "statement": 4000,
    "explanation": 8000,
}


def can_edit(user):
    return bool(
        user.is_authenticated
        and user.is_active
        and (is_superadmin(user) or user.has_perm("knowledge.change_knowledgeentry"))
    )


def require_project(user):
    if not user.is_authenticated or not user.is_active:
        raise PermissionDenied("请先登录有效账号")
    pid = selected_project_id()
    if not Project.objects.filter(pk=pid, is_active=True).exists():
        raise PermissionDenied("项目已停用")
    if (
        pid != 1
        and not is_superadmin(user)
        and not ProjectMembership.objects.filter(
            project_id=pid, user_id=user.pk
        ).exists()
    ):
        raise PermissionDenied("项目访问权限已撤回")
    return pid


def visible_entries(user, manage=False, domains=None):
    pid = require_project(user)
    own = Q(project_tag_id=pid)
    if not (manage and can_edit(user)):
        own &= Q(status="published")
    # Public material is an explicit reusable source, not an all-project query.
    qs = KnowledgeEntry._base_manager.filter(
        own | Q(project_tag_id=1, status="published")
    )
    return (
        qs.filter(domain__in=validate_domains(domains)) if domains is not None else qs
    )


def serialize(entry):
    return {
        **{name: getattr(entry, name) for name in TEXT_FIELDS},
        **{
            name: getattr(entry, name)
            for name in (
                "id",
                "conditions",
                "exceptions",
                "aliases",
                "sources",
                "status",
                "revision",
            )
        },
        "projectTagId": entry.project_tag_id,
        "domain": entry.domain,
        "ruleKind": entry.rule_kind,
        "ruleConfig": entry.rule_config,
        "updatedAt": entry.updated_at.isoformat(),
    }


def search_entries(
    user, query="", limit=8, category="", offset=0, manage=False, domains=None
):
    if not isinstance(query, str) or len(query) > 300:
        raise ValidationError("检索词最多 300 个字符")
    all_visible = visible_entries(user, manage)
    qs = visible_entries(user, manage, domains)
    categories = sorted(set(qs.values_list("category", flat=True)))
    if category:
        qs = qs.filter(category=category)
    terms = search_terms(query)
    if terms:
        match = Q()
        for term in terms:
            for field in (
                "title",
                "statement",
                "subject",
                "object",
                "aliases",
                "conditions",
            ):
                match |= Q(**{f"{field}__icontains": term})
        # Individual Chinese terms also match longer natural-language requests.
        candidates = list(qs.filter(match)[:1000])
        if not candidates and len(query) > 3:
            candidates = [
                e
                for e in qs[:1000]
                if any(
                    len(k) >= 2 and k.casefold() in query.casefold()
                    for k in [e.subject, e.object, *e.aliases]
                )
            ]

        def score(entry):
            text = " ".join(
                [
                    entry.title,
                    entry.statement,
                    entry.subject,
                    entry.object,
                    *entry.aliases,
                ]
            ).casefold()
            return sum(
                3 if t in entry.title.casefold() else int(t in text) for t in terms
            )

        candidates.sort(key=lambda e: (-score(e), e.id))
        total = len(candidates)
        rows = candidates[offset : offset + limit]
    else:
        total = qs.count()
        rows = qs.order_by("category", "id")[offset : offset + limit]
    return {
        "items": [serialize(e) for e in rows],
        "total": total,
        "categories": categories,
        "domains": domain_options(all_visible),
        "canEdit": can_edit(user),
    }


def validate_entry(data):
    if not isinstance(data, dict):
        raise ValidationError("条目必须是对象")
    allowed = {
        *TEXT_FIELDS,
        "conditions",
        "exceptions",
        "aliases",
        "sources",
        "status",
        "ruleKind",
        "ruleConfig",
        "revision",
        "domain",
    }
    if set(data) - allowed:
        raise ValidationError("包含未知知识字段")
    clean = {"domain": validate_domain(data.get("domain", "geology"))}
    for field, maximum in TEXT_FIELDS.items():
        value = data.get(field, "")
        if not isinstance(value, str) or len(value) > maximum:
            raise ValidationError(f"{field} 类型或长度错误")
        if field != "explanation" and not value.strip():
            raise ValidationError(f"{field} 不能为空")
        clean[field] = value.strip()
    for field in ("conditions", "exceptions", "aliases"):
        values = data.get(field, [])
        if (
            not isinstance(values, list)
            or len(values) > 40
            or any(not isinstance(v, str) or len(v) > 1000 for v in values)
        ):
            raise ValidationError(f"{field} 必须是最多 40 项的文本列表")
        clean[field] = [v.strip() for v in values if v.strip()]
    sources = data.get("sources", [])
    if not isinstance(sources, list) or len(sources) > 20:
        raise ValidationError("来源最多 20 条")
    clean_sources = []
    for source in sources:
        if not isinstance(source, dict) or set(source) - {
            "title",
            "url",
            "locator",
            "excerpt",
        }:
            raise ValidationError("来源格式错误")
        item = {}
        for key, maximum in (
            ("title", 300),
            ("url", 1000),
            ("locator", 500),
            ("excerpt", 1200),
        ):
            value = source.get(key, "")
            if not isinstance(value, str) or len(value) > maximum:
                raise ValidationError("来源文本超出长度")
            item[key] = value.strip()
        if not item["title"] or not (item["url"] or item["locator"]):
            raise ValidationError("来源须有标题和链接或章节定位")
        if item["url"]:
            URLValidator(schemes=["http", "https"])(item["url"])
        clean_sources.append(item)
    clean["sources"] = clean_sources
    status = data.get("status", "draft")
    if status not in {"draft", "published", "retired"}:
        raise ValidationError("无效发布状态")
    if status == "published" and not clean_sources:
        raise ValidationError("发布知识需要可核查来源")
    clean["status"] = status
    from .rules import validate_rule

    clean["rule_kind"], clean["rule_config"] = validate_rule(
        data.get("ruleKind", "none"), data.get("ruleConfig", {})
    )
    if len(json.dumps(clean, ensure_ascii=False)) > 30000:
        raise ValidationError("条目内容过长")
    return clean


def check_constraints(user, facts, entry_ids=None, domains=None):
    from .rules import evaluate

    try:
        size = len(json.dumps(facts, ensure_ascii=False, allow_nan=False))
    except (ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise ValidationError("事实包含无效数值或过深嵌套") from exc
    if not isinstance(facts, dict) or size > 20000:
        raise ValidationError("事实须为不超过 20000 字符的对象")
    qs = visible_entries(user, domains=domains).exclude(rule_kind="none")
    if entry_ids is not None:
        if (
            not isinstance(entry_ids, list)
            or len(entry_ids) > 50
            or any(type(i) is not int or i < 1 for i in entry_ids)
        ):
            raise ValidationError("entryIds 须为最多 50 个知识 ID")
        accessible = set(
            visible_entries(user, domains=domains)
            .filter(pk__in=entry_ids)
            .values_list("pk", flat=True)
        )
        if set(entry_ids) != accessible:
            raise PermissionDenied("知识不存在或无权访问")
        qs = qs.filter(pk__in=entry_ids)
    findings = []
    for entry in qs[:100]:
        status, detail = evaluate(entry.rule_kind, entry.rule_config, facts)
        findings.append(
            {
                "entryId": entry.id,
                "title": entry.title,
                "status": status,
                "detail": detail,
                "revision": entry.revision,
                "sources": entry.sources,
            }
        )
    return {"findings": findings, "checked": len(findings)}
