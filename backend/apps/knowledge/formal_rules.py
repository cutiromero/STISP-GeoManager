"""Preserve exact frozen semantics across an explicit administrative publication."""

from copy import deepcopy
from .models import KnowledgeRevision


def semantics(value):
    config = deepcopy(value.get("ruleConfig") or {})
    config.pop("formalRelease", None)
    return {
        key: value.get(key)
        for key in (
            "id",
            "projectTagId",
            "domain",
            "category",
            "subject",
            "predicate",
            "object",
            "explanation",
            "ruleKind",
            "aliases",
            "statement",
            "conditions",
            "exceptions",
            "sources",
        )
    } | {"ruleConfig": config}


def published_predecessor(entry, current, revision):
    release = (current.get("ruleConfig") or {}).get("formalRelease") or {}
    if (
        current.get("status") != "published"
        or release.get("previousRevision") != revision
    ):
        return None
    previous = KnowledgeRevision._base_manager.filter(
        entry_id=entry.id, project_tag_id=entry.project_tag_id, revision=revision
    ).first()
    if previous is None:
        return None
    value = deepcopy(previous.snapshot)
    if value.get("revision") != revision or semantics(current) != semantics(value):
        return None
    return value
