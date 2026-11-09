"""Run-scoped, server-enforced tool selectors; independent of model wording."""

import re
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q

from apps.knowledge.domains import DOMAINS, query_domains, validate_domains

KNOWLEDGE_TOOLS = {
    "search_knowledge",
    "read_knowledge_document",
    "check_knowledge_constraints",
}

# Configuration: only explicit continuation wording inherits an earlier topic.
CONTINUATION_TOPIC = re.compile(
    r"继续|接着|上轮|上次|刚才|上述|前面|这个|这张|这幅|这份|该资料|该数据|同一|它"
    r"|跑完|算完|完成了吗|进度|结果如何|结果怎么样"
)


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
    resolved = (getattr(run, "knowledge_selection", None) or {}).get("_resolvedDomains")
    if resolved is not None:
        # Only the server records a research task's actual automatic routing.
        return validate_domains(resolved)
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
    if not current and CONTINUATION_TOPIC.search(run.prompt):
        prior = run.conversation.runs.all()
        if run.id is not None:
            prior = prior.filter(id__lt=run.id)
        for previous in prior.order_by("-id")[:1]:
            saved = (previous.knowledge_selection or {}).get("_resolvedDomains")
            current = (
                validate_domains(saved)
                if saved is not None
                else query_domains(previous.prompt)
            )
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
        from .deleted_resources import TERMINAL

        receipts = {
            item.get("formerResourceId")
            for item in run.execution_state.get("deletedResources", [])
            if item.get("platformDeletion") is True
            and item.get("historyReadableByOwner") is True
            and item.get("status") == "deleted"
            and item.get("projectTagId") == run.project_tag_id
        }
        inputs = set()
        for item in task.input_records.all():
            identity = item.resource_id
            removed = item.snapshot.get("deletedResource", {})
            if (
                identity is None
                and run.status in TERMINAL
                and removed.get("platformDeletion") is True
                and removed.get("formerResourceId") in receipts
            ):
                identity = removed["formerResourceId"]
            inputs.add(identity)
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
        or any(type(i) is not int or i < 1 for i in version_ids)
        or (algorithm_mode == "manual") != bool(version_ids)
        or (data_mode == "manual" and not selected)
        or (data_mode == "auto" and selected)
    ):
        raise ValidationError(
            "手选算法须选择至少一个版本，手选数据须选择资源；自动模式请清空选择"
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
            "research_intent",
            "research_workflow",
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
        check_evidence(source, user, policy, history=True)
        from .research_intents import authorize_run

        authorize_run(source, user, policy, history=True)


def check_conversation_history(runs, user, policy):
    """Authorize each exact history source once within this response only."""
    from .tools import check_evidence
    from .research_intents import authorize_run

    if not runs:
        return set()
    conversation = runs[0].conversation
    identities = {run.pk for run in runs}
    legacy_ceiling = 0
    for run in runs:
        marker = (run.knowledge_selection or {}).get("_contextRunIds")
        if isinstance(marker, list):
            identities.update(i for i in marker if type(i) is int and i < run.id)
        else:
            legacy_ceiling = max(legacy_ceiling, run.id)
    # Keep the original successful-ancestor and conversation boundaries.
    ancestors = (
        conversation.runs.filter(status="succeeded")
        .filter(Q(pk__in=identities) | Q(pk__lt=legacy_ceiling))
        .exclude(pk__in=[run.pk for run in runs])
        .only(
            "evidence",
            "prompt",
            "knowledge_selection",
            "compute_intent",
            "research_intent",
            "research_workflow",
            "conversation_id",
            "owner_id",
            "project_tag_id",
            "resource_ids",
            "algorithm_selection_mode",
            "algorithm_version_ids",
            "data_selection_mode",
        )
    )
    sources = {source.pk: source for source in ancestors}
    sources.update({run.pk: run for run in runs})
    for source in sources.values():
        check_evidence(source, user, policy, history=True)
        authorize_run(source, user, policy, history=True)
    return {run.pk for run in runs}


def source_resource_ids(source):
    """Read only documented resource positions, never arbitrary integers in results."""
    identities = list(source.resource_ids or [])
    for intent in (source.compute_intent or {}, source.research_intent or {}):
        identities.extend(intent.get("inputs", {}).values())
    for evidence in source.evidence:
        if evidence.get("resourceId") is not None:
            identities.append(evidence["resourceId"])
        result = evidence.get("result", {})
        if not isinstance(result, dict):
            continue
        rows = [result]
        if evidence.get("tool") == "search_resources":
            identities.extend(
                item.get("id")
                for item in result.get("items", [])
                if isinstance(item, dict)
            )
        if evidence.get("tool") == "list_compute_tasks":
            rows = result.get("items", [])
        for row in rows:
            if not isinstance(row, dict):
                continue
            identities.append(row.get("resourceId"))
            outputs = row.get("outputs", [])
            if isinstance(row.get("output"), dict):
                outputs = [row["output"]]
            identities.extend(
                item.get("resourceId") for item in outputs if isinstance(item, dict)
            )
    return {
        identity for identity in identities if type(identity) is int and identity > 0
    }


def _require_bound_resource(identity, current, user, policy):
    from apps.compute.models import ComputeImport
    from .compute_tools import authorized_task

    # A run may continue its own actual calculation, but cannot borrow another
    # turn's or another workflow's private intermediate resources.
    if current.pk:
        for link in current.compute_followups.select_related("task"):
            task = link.task
            if not (
                task.input_records.filter(resource_id=identity).exists()
                or ComputeImport.objects.filter(
                    output__task=task, status="ready", resource_id=identity
                ).exists()
            ):
                continue
            require_task_selection(
                current, authorized_task(user, link.task_id, policy, run=current)
            )
            return
    if current.research_workflow_id or (current.research_intent or {}).get(
        "_uploadBatchId"
    ):
        from .workflow_resources import resolve_run_resource

        resolve_run_resource(user, policy, identity, current)
        return
    raise PermissionDenied("历史资料不在当前任务可复用范围内")


def check_context_evidence(source, current, user, policy):
    """Model reuse is stricter than the ACL-only, read-only history view."""
    from .compute_tools import authorized_task
    from .research_intents import authorize_run
    from .resource_discovery import discover_resources
    from .tools import check_evidence

    same_run = source.pk is not None and source.pk == current.pk
    check_evidence(source, user, policy, history=not same_run)
    authorize_run(source, user, policy, history=not same_run)
    if not same_run and any(
        item.get("tool") == "summarize_resource_catalog" for item in source.evidence
    ):
        # Old totals lack per-resource provenance and must be queried afresh.
        raise PermissionDenied("历史目录统计需要按当前范围重新查询")
    identities = source_resource_ids(source)
    if identities:
        candidates = (
            identities & set(current.resource_ids)
            if current.resource_ids
            else identities
        )
        visible = (
            set()
            if not candidates
            or (current.data_selection_mode == "manual" and not current.resource_ids)
            else set(
                discover_resources(
                    user,
                    policy,
                    sorted(candidates),
                ).values_list("id", flat=True)
            )
        )
        for identity in identities - visible:
            _require_bound_resource(identity, current, user, policy)
    for evidence in source.evidence:
        if evidence.get("tool") not in {
            "execute_operator",
            "get_compute_task",
            "list_compute_tasks",
            "import_compute_result",
            "read_compute_output",
        }:
            continue
        result = evidence.get("result", {})
        rows = (
            result.get("items", [])
            if evidence["tool"] == "list_compute_tasks"
            else [result]
        )
        for row in rows:
            if isinstance(row, dict) and row.get("taskId"):
                context = (
                    {} if evidence["tool"] == "list_compute_tasks" else {"run": current}
                )
                require_task_selection(
                    current, authorized_task(user, row["taskId"], policy, **context)
                )


def reusable_context_sources(previous, current, user, policy):
    """Return the exact checked ancestry so callers need not query it twice."""
    try:
        sources = history_sources(previous)
        if not history_compatible(previous, current, sources=sources):
            return None
        for source in sources:
            check_context_evidence(source, current, user, policy)
    except (PermissionDenied, ValidationError, ValueError):
        return None
    return sources


def context_reusable(previous, current, user, policy):
    return reusable_context_sources(previous, current, user, policy) is not None


def check_context_sources(run, user, policy):
    """Recheck only sources actually sent to this model, not unrelated old turns."""
    from .models import AgentRun

    check_context_evidence(run, run, user, policy)
    marker = (run.knowledge_selection or {}).get("_contextRunIds", [])
    identities = {identity for identity in marker if type(identity) is int}
    sources = list(
        AgentRun.objects.filter(
            pk__in=identities,
            conversation_id=run.conversation_id,
            owner_id=run.owner_id,
            project_tag_id=run.project_tag_id,
            id__lt=run.id,
        )
    )
    if len(sources) != len(identities):
        raise PermissionDenied("已发送的历史来源发生变化，请重新发起分析")
    for source in sources:
        if not history_compatible(source, run):
            raise PermissionDenied("已发送的历史来源超出当前选择，请重新发起分析")
        check_context_evidence(source, run, user, policy)


def sanitize_context_state(run, user, policy, state=None):
    """Drop an unverifiable history prefix while retaining this run's real tools."""
    from .models import AgentRun

    state = dict(run.execution_state if state is None else state)
    if not state or run.conversation.mode != "agent":
        return state
    check_context_evidence(run, run, user, policy)
    messages, index = list(state.get("messages", [])), state.get("currentIndex")
    if type(index) is not int or not 0 <= index < len(messages):
        raise ValidationError("任务续接上下文无效，请重新发起分析")
    marker = (run.knowledge_selection or {}).get("_contextRunIds")
    identities = (
        {identity for identity in marker if type(identity) is int}
        if isinstance(marker, list)
        else set()
    )
    sources = list(
        AgentRun.objects.filter(
            pk__in=identities,
            conversation_id=run.conversation_id,
            owner_id=run.owner_id,
            project_tag_id=run.project_tag_id,
            id__lt=run.id,
        )
    )
    verified = (
        bool(identities)
        and len(sources) == len(identities)
        and all(context_reusable(source, run, user, policy) for source in sources)
    )
    if not index or not verified:
        state.update(messages=messages[index:], currentIndex=0)
        run.knowledge_selection = {
            **(run.knowledge_selection or {}),
            "_contextRunIds": [],
        }
    return state


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


def history_compatible(previous, current, *, sources=None):
    """Exclude entire old answers if their citations fall outside this turn."""
    from .research_intents import history_compatible as research_compatible

    if not research_compatible(previous, current):
        return False
    if sources is None:
        sources = history_sources(previous)
    allowed_knowledge = set(knowledge_domains(current))
    for source in sources:
        if not source_knowledge_domains(source) <= allowed_knowledge:
            return False
    versions = algorithm_ids(current)
    if versions is not None:
        from .citations import source_locators

        listed_versions = {
            location["versionId"]
            for source in sources
            for item in source.evidence
            if item.get("tool") == "list_compute_algorithms"
            for location in source_locators(item)
            if "versionId" in location
        }
        listed_versions.update(
            source.compute_intent["versionId"]
            for source in sources
            if source.compute_intent.get("versionId")
        )
        if not listed_versions <= set(versions):
            return False
    if versions is not None or current.resource_ids:
        tasks = set()
        for ev in [e for source in sources for e in source.evidence]:
            if ev.get("tool") in {
                "execute_operator",
                "get_compute_task",
                "list_compute_tasks",
                "import_compute_result",
                "read_compute_output",
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
