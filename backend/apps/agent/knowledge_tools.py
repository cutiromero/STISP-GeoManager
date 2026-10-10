"""Bounded, source-labelled knowledge retrieval for the data agent."""

import json

from django.core.exceptions import PermissionDenied, ValidationError

MAX_BYTES = 24000


def search_knowledge(run, user, query):
    from apps.knowledge.library import search_documents, visible_documents
    from apps.knowledge.services import search_entries, visible_entries
    from apps.knowledge.weknora_client import WeKnoraError
    from .selections import knowledge_domains, require_knowledge

    require_knowledge(run)
    domains = knowledge_domains(run, query)
    structured = search_entries(user, query, limit=8, domains=domains)
    try:
        document_search = search_documents(user, query, limit=6, domains=domains)
    except WeKnoraError as exc:
        document_search = {"items": [], "available": False, "detail": str(exc)}
    references = {(e["id"], e["revision"]) for e in structured["items"]}
    if references and not references <= set(
        visible_entries(user, domains=domains)
        .filter(pk__in=[identity for identity, _ in references])
        .values_list("id", "revision")
    ):
        raise PermissionDenied("知识依据或分区已变化，请重新检索")
    result = {
        "items": [],
        "domains": domains,
        "documents": [],
        "documentSearch": {
            "available": bool(document_search["available"]),
            "detail": document_search["detail"],
        },
        "truncated": False,
        "citationGuide": "只使用各条目的citation引用；id/documentId是存储标识，不是证据编号。",
        "retrievalGuide": "documents已含知识文献原文；documentId不是数据resourceId。需要更多原文时使用read_knowledge_document(documentId,offset,limit)，或以具体主题再次search_knowledge；不要传给read_document。",
    }
    pairs = []

    def add(item, collection, limit):
        number = len(run.evidence) + len(pairs) + 1
        item = {**item, "evidenceId": number, "citation": f"[证据 {number}]"}
        result[collection].append(item)
        if len(json.dumps(result, ensure_ascii=False).encode()) > limit:
            result[collection].pop()
            result["truncated"] = True
            return
        pairs.append((None, {collection: [item]}))

    # Reserve half of the bounded model result for document passages when present.
    structured_limit = MAX_BYTES // 2 if document_search["items"] else MAX_BYTES
    for entry in structured["items"]:
        add(entry, "items", structured_limit)
    documents = {
        doc.id: doc
        for doc in visible_documents(user, domains).filter(
            pk__in=[item["documentId"] for item in document_search["items"]]
        )
    }
    for hit in document_search["items"]:
        doc = documents.get(hit["documentId"])
        if doc is None:
            raise PermissionDenied("知识资料访问权限已变化，请重新检索")
        add(
            {
                **hit,
                "content": hit["content"][:1400],
                "excerptTruncated": len(hit["content"]) > 1400,
                "documentSha256": doc.sha256,
                "sourceKind": "document_excerpt",
            },
            "documents",
            MAX_BYTES,
        )
    # An empty or unavailable search is itself evidence, not a fabricated source.
    return result, pairs or [(None, result)]


def read_knowledge_document(run, user, args):
    from apps.knowledge.library import read_document
    from apps.knowledge.weknora_client import WeKnoraError
    from .selections import knowledge_domains, require_knowledge

    require_knowledge(run)
    domains = knowledge_domains(run)
    try:
        result = read_document(
            user,
            args.get("documentId"),
            offset=args.get("offset", 0),
            limit=args.get("limit", 8000),
            domains=domains,
        )
    except WeKnoraError as exc:
        if exc.status in {403, 404}:
            raise PermissionDenied(str(exc)) from exc
        raise ValidationError(str(exc)) from exc
    check_document_evidence(
        user, [(result["documentId"], result["documentSha256"])], domains=domains
    )
    number = len(run.evidence) + 1
    item = {
        **result,
        "sourceKind": "document_excerpt",
        "evidenceId": number,
        "citation": f"[证据 {number}]",
    }
    response = {"documents": [item]}
    return response, [(None, response)]


def check_document_evidence(user, document_refs, domains=None):
    from apps.knowledge.library import visible_documents

    expected = set(document_refs)
    if not expected:
        return
    actual = set(
        visible_documents(user, domains)
        .filter(pk__in=[identity for identity, _ in expected])
        .exclude(status__in=["failed", "cancelled"])
        .values_list("id", "sha256")
    )
    if not expected <= actual:
        raise PermissionDenied("知识资料已更新或访问权限已变化，请重新检索")
