"""Run-scoped, server-enforced tool selectors; independent of model wording."""

from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError

from apps.knowledge.domains import DOMAINS, query_domains, validate_domains

KNOWLEDGE_TOOLS = {
    "search_knowledge",
    "read_knowledge_document",
    "check_knowledge_constraints",
}


def knowledge_selection(run):
    value = getattr(run, "knowledge_selection", None) or {}
    return {"mode": value.get("mode", "auto"), "domains": value.get("domains", [])}


def knowledge_domains(run, query=""):
    value = knowledge_selection(run)
    if value["mode"] == "none":
        return []
    if value["mode"] == "manual":
        return validate_domains(value["domains"])
    if value["mode"] == "all":
        return list(DOMAINS)
    # The current user topic sets a ceiling. Tool queries cannot expand it.
    topic = run.prompt
    version_ids = algorithm_ids(run) or []
    if run.compute_intent.get("versionId"):
        version_ids = [*version_ids, run.compute_intent["versionId"]]
    if version_ids:
        topic += " " + " ".join(
            v.algorithm.name for v in available_versions() if v.id in version_ids
        )
    current = query_domains(topic)
    if not current:
        prior = run.conversation.runs.all()
        if run.id is not None:
            prior = prior.filter(id__lt=run.id)
        for previous in prior.order_by("-id")[:1]:
            current = query_domains(previous.prompt)
    return current or query_domains(query) or list(DOMAINS)


def require_knowledge(run):
    if knowledge_selection(run)["mode"] == "none":
        raise PermissionDenied("本轮已选择不参考知识库")


def algorithm_ids(run):
    if getattr(run, "algorithm_selection_mode", "auto") != "manual":
        return None
    return list(getattr(run, "algorithm_version_ids", []) or [])


def require_algorithm(run, version_id):
    selected = algorithm_ids(run)
    if selected is not None and version_id not in selected:
        raise PermissionDenied("算法不在本轮手选范围内")


def require_task_selection(run, task):
    require_algorithm(run, task.version_id)
    if run.resource_ids:
        inputs = set(task.input_records.values_list("resource_id", flat=True))
        if not inputs <= set(run.resource_ids):
            raise PermissionDenied("任务输入数据不在本轮手选范围内")


def scoped_task_ids(run, identities):
    """Resolve task identity and original inputs, never trust old result metadata."""
    from apps.compute.models import ComputeTask

    valid = set()
    for identity in identities:
        try:
            valid.add(UUID(str(identity)))
        except (ValueError, TypeError, AttributeError):
            continue
    allowed = set()
    for task in ComputeTask.objects.filter(
        pk__in=valid, owner_id=run.owner_id, project_tag_id=run.project_tag_id
    ).prefetch_related("input_records"):
        try:
            require_task_selection(run, task)
        except PermissionDenied:
            continue
        allowed.add(str(task.id))
    return allowed


def available_versions():
    from apps.compute.models import AlgorithmVersion
    from apps.compute.services import allowed_algorithms, agent_algorithm_allowed

    return [
        version
        for version in AlgorithmVersion.objects.select_related("algorithm")
        .filter(
            algorithm__in=allowed_algorithms(),
            algorithm__enabled=True,
            status="published",
        )
        .order_by("algorithm__name", "-created_at", "-id")
        if agent_algorithm_allowed(version)
    ]


def algorithm_options():
    return [
        {
            "versionId": v.id,
            "algorithmId": v.algorithm_id,
            "name": v.algorithm.name,
            "version": v.version,
            "description": v.algorithm.description[:800],
        }
        for v in available_versions()[:200]
    ]


def normalize(value, selected):
    knowledge = value.get("knowledgeSelection", {"mode": "auto", "domains": []})
    if (
        not isinstance(knowledge, dict)
        or set(knowledge) != {"mode", "domains"}
        or knowledge.get("mode") not in {"auto", "manual", "all", "none"}
    ):
        raise ValidationError("知识调用方式无效")
    domains = validate_domains(knowledge["domains"])
    if (knowledge["mode"] == "manual") != bool(domains):
        raise ValidationError("手选知识须选择领域；其他模式请清空领域选择")
    algorithm_mode = value.get("algorithmSelectionMode", "auto")
    version_ids = value.get("algorithmVersionIds", [])
    data_mode = value.get("dataSelectionMode", "manual" if selected else "auto")
    if algorithm_mode not in {"auto", "manual"} or data_mode not in {"auto", "manual"}:
        raise ValidationError("算法或数据选择方式无效")
    if (
        not isinstance(version_ids, list)
        or len(version_ids) > 3
        or any(type(i) is not int or i < 1 for i in version_ids)
        or (algorithm_mode == "manual") != bool(version_ids)
        or (data_mode == "manual" and not selected)
        or (data_mode == "auto" and selected)
    ):
        raise ValidationError(
            "手选算法须选择1至3个版本，手选数据须选择资源；自动模式请清空选择"
        )
    return {
        "knowledge_selection": {"mode": knowledge["mode"], "domains": domains},
        "algorithm_selection_mode": algorithm_mode,
        "algorithm_version_ids": sorted(set(version_ids)),
        "data_selection_mode": data_mode,
    }


def validate_selected_versions(selections):
    selected = selections["algorithm_version_ids"]
    if selected and not set(selected) <= {v.id for v in available_versions()}:
        raise PermissionDenied("所选算法版本未发布、已停用或不允许智能体调用")


def serialize(run):
    return {
        "knowledgeSelection": knowledge_selection(run),
        "resolvedKnowledgeDomains": knowledge_domains(run),
        "algorithmSelectionMode": run.algorithm_selection_mode,
        "algorithmVersionIds": list(run.algorithm_version_ids or []),
        "dataSelectionMode": run.data_selection_mode,
        "resourceIds": list(run.resource_ids or []),
    }


def history_sources(run):
    """Persist exact ancestry for new turns; legacy summaries retain a safe ceiling."""
    marker = (run.knowledge_selection or {}).get("_contextRunIds")
    prior = run.conversation.runs.filter(id__lt=run.id, status="succeeded")
    if isinstance(marker, list):
        prior = prior.filter(pk__in=[i for i in marker if type(i) is int])
    # Old turns did not record derived sources. Conservatively include their
    # earlier successful history, because an evidence-free summary can quote it.
    return [
        run,
        *prior.only(
            "evidence",
            "prompt",
            "knowledge_selection",
            "compute_intent",
            "conversation_id",
            "owner_id",
            "project_tag_id",
            "resource_ids",
            "algorithm_selection_mode",
            "algorithm_version_ids",
            "data_selection_mode",
        ),
    ]


def check_history_evidence(run, user, policy):
    from .tools import check_evidence

    for source in history_sources(run):
        check_evidence(source, user, policy)


def source_knowledge_domains(run):
    from apps.knowledge.models import KnowledgeEntry, KnowledgeDocument

    domains, entry_ids, document_ids = set(), set(), set()
    used = False
    for ev in run.evidence:
        if ev.get("tool") not in KNOWLEDGE_TOOLS:
            continue
        used = True
        result = ev.get("result", {})
        for item in [*result.get("items", []), *result.get("findings", [])]:
            identity = item.get("id", item.get("entryId"))
            if type(identity) is int:
                entry_ids.add(identity)
        for item in result.get("documents", []):
            if type(item.get("documentId")) is int:
                document_ids.add(item["documentId"])
    if not used:
        return set()
    domains.update(
        KnowledgeEntry._base_manager.filter(pk__in=entry_ids).values_list(
            "domain", flat=True
        )
    )
    domains.update(
        KnowledgeDocument._base_manager.filter(pk__in=document_ids).values_list(
            "domain", flat=True
        )
    )
    return domains or (set(knowledge_domains(run)) if used else set())


def history_compatible(previous, current):
    """Exclude entire old answers if their citations fall outside this turn."""
    sources = history_sources(previous)
    allowed_knowledge = set(knowledge_domains(current))
    for source in sources:
        if not source_knowledge_domains(source) <= allowed_knowledge:
            return False
    versions = algorithm_ids(current)
    if versions is not None or current.resource_ids:
        tasks = set()
        for ev in [e for source in sources for e in source.evidence]:
            if ev.get("tool") in {
                "execute_operator",
                "get_compute_task",
                "list_compute_tasks",
                "import_compute_result",
            }:
                result = ev.get("result", {})
                rows = (
                    result.get("items", [])
                    if ev["tool"] == "list_compute_tasks"
                    else [result]
                )
                for row in rows:
                    identity = row.get("taskId") if isinstance(row, dict) else None
                    if not identity:
                        return False
                    tasks.add(str(identity))
        if tasks and not tasks <= scoped_task_ids(current, tasks):
            return False
    if current.resource_ids:
        used = {
            e.get("resourceId")
            for source in sources
            for e in source.evidence
            if e.get("resourceId")
        }
        if not used <= set(current.resource_ids):
            return False
    return True
