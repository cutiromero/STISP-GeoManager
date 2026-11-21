"""Workflow knowledge selection and verified citations."""

from django.core.exceptions import PermissionDenied

from .state import parent_run

TOOLS = {"search_knowledge", "read_knowledge_document"}


def initial_knowledge_selection(definition, source_run, goal):
    from apps.agent.selections import knowledge_selection
    from apps.knowledge.domains import DOMAINS, query_domains

    questions = definition.get("skill", {}).get("knowledgeQuestions", [])
    if source_run:
        return knowledge_selection(source_run)
    domains = query_domains(" ".join([goal, *questions])) or list(DOMAINS)
    return {
        "mode": "auto",
        "domains": [],
        "_resolvedDomains": domains,
        "_contextRunIds": [],
    }


def retain(run, tool, pairs):
    from apps.agent.models import AgentRun
    from apps.agent.tools import evidence_items

    entries = evidence_items(run, tool, pairs)
    if entries:
        for entry in entries:
            entry["workflowDiscovery"] = True
        saved = AgentRun._base_manager.filter(
            pk=run.pk,
            owner_id=run.owner_id,
            project_tag_id=run.project_tag_id,
            research_workflow_id=run.research_workflow_id,
            knowledge_selection=run.knowledge_selection,
            evidence=run.evidence,
            cancel_requested=False,
        ).update(evidence=[*run.evidence, *entries])
        if saved != 1:
            raise PermissionDenied("本次知识范围或依据已变化，请重新检索")
    return entries


def authorized_entries(workflow, user=None, *, history=False):
    from apps.agent.knowledge_tools import check_knowledge_evidence
    from apps.agent.policy import fresh_user
    from apps.agent.selections import knowledge_domains, require_knowledge

    from .execution_session import session

    bind = workflow.parameters.get("_businessFlow", {})
    if not bind.get("runId"):
        return []
    run = parent_run(workflow)
    # Old sessions recorded an explicit set of citation IDs. A new workflow
    # tool call marks its own entries, separate from earlier chat evidence.
    old_ids = set(session(workflow).get("loop", {}).get("knowledgeEvidenceIds", []))
    entries = [
        entry
        for entry in run.evidence
        if entry["tool"] in TOOLS
        and (entry.get("workflowDiscovery") or entry["id"] in old_ids)
    ]
    if not old_ids <= {entry["id"] for entry in entries}:
        raise PermissionDenied("业务流知识依据已变化，请重新检索")
    if not entries:
        return []
    require_knowledge(run)
    user = user if user is not None else fresh_user(workflow.owner_id)
    from apps.agent.capability_catalog import enabled
    from apps.agent.policy import require_access

    policy = require_access(user, "agent", run.model)
    if not policy["allowDocuments"] and any(
        entry["result"].get("documents") for entry in entries
    ):
        raise PermissionDenied("文档读取权限已关闭")
    if any(
        not enabled(tool, user, policy, run=run)
        for tool in {entry["tool"] for entry in entries}
    ):
        raise PermissionDenied("知识工具访问权限已变化")
    check_knowledge_evidence(
        user,
        {
            (item["id"], item["revision"])
            for entry in entries
            for item in entry["result"].get("items", [])
        },
        {
            (item["documentId"], item["documentSha256"])
            for entry in entries
            for item in entry["result"].get("documents", [])
        },
        domains=knowledge_domains(run),
        history=history,
    )
    return entries


def evidence_rows(workflow):
    rows = []
    for entry in authorized_entries(workflow)[-8:]:
        result = entry["result"]
        item = (result.get("items") or result["documents"])[0]
        evidence = {
            key: item[key]
            for key in (
                "id",
                "revision",
                "documentId",
                "sourceUrl",
                "chunkId",
                "domain",
            )
            if key in item
        }
        if "sourceUrl" in evidence:
            evidence["sourceUrl"] = str(evidence["sourceUrl"] or "")[:320]
        evidence["excerpt"] = str(item.get("statement") or item.get("content") or "")[
            :450
        ]
        for key in ("conditions", "exceptions", "sources"):
            if item.get(key):
                evidence[key] = [str(value)[:120] for value in item[key][:3]]
        rows.append(
            {
                "id": f"knowledge-{entry['id']}",
                "kind": "knowledge",
                "title": (str(item.get("title") or "知识依据"))[:200],
                "result": evidence,
            }
        )
    return rows
