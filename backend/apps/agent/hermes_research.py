"""Research plans and compute tools for Hermes sessions."""

import hashlib
import json
from functools import lru_cache
from time import monotonic, sleep

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db.models import Q

from apps.business_flows.models import BusinessFlowVersion
from apps.business_flows.scopes import catalog_flows
from apps.compute import services
from apps.compute.models import AlgorithmVersion, ComputeOutput, ComputeTask
from apps.compute.packages import ComputeError
from .capability_catalog import enabled

PERMISSIONS = {
    "get_research_workflow": "list_business_flows",
    "submit_research_compute": "execute_operator",
    "get_research_compute": "get_compute_task",
    "read_research_output": "read_compute_output",
    "register_research_output": "import_compute_result",
    "inspect_research_operator": "execute_operator",
    "list_research_geology_rules": "list_business_flows",
    "prepare_research_geology_changes": "execute_operator",
}

SUGGESTED_TOOLS = {
    "agent": ("search_resources", "describe_resource", "search_knowledge"),
    "operator": (
        "list_compute_algorithms",
        "submit_research_compute",
        "get_research_compute",
    ),
    "human": ("clarify",),
    "result": ("read_research_output", "get_platform_link"),
}

DOMAIN_SKILLS = {
    "geology-logic-reasoning": "geology-research",
    "huanjiang-landcover": "remote-sensing-monitoring",
    "spartina-distribution": "remote-sensing-monitoring",
    "wildfire-history-observation": "remote-sensing-monitoring",
}

GEOLOGY_ALGORITHMS = {
    "check": "geology-multi-check",
    "apply": "geology-multi-apply",
    "recheck": "geology-multi-check",
    "relations": "geology-multi-relations",
    "prospect": "geology-multi-prospect",
}

GEOLOGY_ACTIONS = {
    "inputs": "核对岩性、构造与蚀变资料的范围、比例尺和字段含义。",
    "check": "结合空间关系、属性和区域地质知识定位值得复核的图面问题。",
    "apply": "依据图斑和关系证据整理处置建议，请用户选择拟应用的修改。",
    "recheck": "按相同范围和统计口径比较处置前后的成果。",
    "relations": "根据交汇几何与交切证据梳理构造关系。",
    "prospect": "综合岩性、构造和蚀变信息，标出建议核查的找矿线索。",
    "finish": "汇总实际产出的图件、发现、证据和后续调查行动。",
}


@lru_cache(maxsize=1)
def native_contracts():
    path = settings.PROGRAM_ROOT / "deploy/hermes/plugin/contracts.json"
    return {
        name: contract
        for name, contract in json.loads(path.read_text(encoding="utf-8")).items()
        if "inputSchema" in contract
    }


def tool_allowed(name, user, policy, *, run=None):
    return enabled(PERMISSIONS.get(name, name), user, policy, run=run)


def workflow_plan(version_id=None, name=None):
    visible = catalog_flows()
    if version_id is None and name:
        flow = visible.filter(Q(code__iexact=name) | Q(name__iexact=name)).first()
        version_id = flow.current_version_id if flow else None
    version = (
        BusinessFlowVersion._base_manager.select_related("flow")
        .filter(pk=version_id, status="published", flow__in=visible)
        .first()
    )
    if version is None:
        raise ComputeError("请选择当前项目可用的已发布业务流版本", 404)
    definition = version.definition
    geology = definition["adapter"] == "geology_generic"
    nodes = []
    for node in definition["nodes"]:
        suggestion = (
            GEOLOGY_ACTIONS.get(node["id"], node["title"])
            if geology
            else node.get("description") or node["title"]
        )
        step = {
            "id": node["id"],
            "title": node["title"],
            "direction": suggestion,
            "after": node["dependsOn"],
            "dataRoles": node["dataRoles"],
            "suggestedTools": SUGGESTED_TOOLS.get(node["kind"], ()),
        }
        if geology and node["id"] in GEOLOGY_ALGORITHMS:
            step["candidateAlgorithm"] = GEOLOGY_ALGORITHMS[node["id"]]
        if node.get("algorithmVersionId"):
            step["candidateAlgorithmVersionId"] = node["algorithmVersionId"]
            step["candidateParameters"] = node.get("parameters", {})
            step["candidateInputBindings"] = node.get("inputBindings", {})
        if geology and node["id"] == "apply":
            step["suggestedTools"] = (
                "prepare_research_geology_changes",
                *SUGGESTED_TOOLS["operator"],
            )
        if node["kind"] == "human" or node["review"]["human"]:
            step["consultResearcher"] = True
        nodes.append(step)
    domain_skill = DOMAIN_SKILLS.get(version.flow.code)
    return {
        "versionId": version.pk,
        "name": version.flow.name,
        "description": version.flow.description,
        "dataRoles": [
            {key: row[key] for key in ("key", "label", "dataTypes")}
            for row in definition["inputRequirements"]
        ],
        "suggestedSteps": nodes,
        **({"domainSkill": domain_skill} if domain_skill else {}),
        **({"ruleSourcesTool": "list_research_geology_rules"} if geology else {}),
        "deliverables": definition["outputRequirements"],
        "knowledgeQuestions": definition.get("skill", {}).get("knowledgeQuestions", []),
    }


def task_prefix(session):
    return f"mh-{session.pk.hex}-"


def session_task(session, user, policy, task_id):
    from .compute_tools import authorized_task

    matching = ComputeTask.objects.filter(
        pk=task_id, owner=user, idempotency_key__startswith=task_prefix(session)
    ).exists()
    if not matching:
        raise ComputeError("请选择本会话中的计算任务", 404)
    return authorized_task(
        user,
        task_id,
        policy,
        resolve_input=lambda task, item: resolve_input(
            session, user, policy, task.version, item.key, item.resource_id
        ),
    )


def authorize_import(record, session_id):
    from .models import HermesSession
    from .policy import fresh_user, require_access

    task = record.output.task
    session = HermesSession._base_manager.filter(
        pk=session_id,
        owner_id=record.requested_by_id,
        project_tag_id=task.project_tag_id,
        mode="agent",
    ).first()
    if session is None:
        raise PermissionDenied("请从科研会话重新登记此成果")
    user = fresh_user(session.owner_id)
    policy = require_access(user, "agent")
    if not tool_allowed("register_research_output", user, policy):
        raise PermissionDenied("请使用已获授权的成果登记服务")
    session_task(session, user, policy, task.pk)


def geology_rule_sources(user, policy):
    from .resource_discovery import acl_resources

    return acl_resources(user, policy).filter(
        data_type="table",
        code__startswith="geology-multi-rules",
    )


def resolve_input(session, user, policy, version, key, identity):
    from .hermes_geology import APPROVAL_SOURCE
    from .resource_discovery import acl_resources, resolve_discoverable_resource

    if (
        key == "approved_changes"
        and version.algorithm.identifier == GEOLOGY_ALGORITHMS["apply"]
    ):
        receipt = (
            acl_resources(user, policy)
            .filter(
                pk=identity,
                maintainer=user,
                source__startswith=f"{APPROVAL_SOURCE}{session.pk.hex}:",
            )
            .first()
        )
        if receipt is not None:
            return receipt
    if key == "rules" and version.algorithm.identifier in GEOLOGY_ALGORITHMS.values():
        rules = geology_rule_sources(user, policy).filter(pk=identity).first()
        if rules is not None:
            return rules
    return resolve_discoverable_resource(user, policy, identity)


def published_version(identity=None, identifier=None):
    candidates = (
        AlgorithmVersion.objects.select_related("algorithm")
        .filter(
            status="published",
            algorithm__enabled=True,
            algorithm__in=services.allowed_algorithms(),
        )
        .filter(
            Q(manifest__agent__enabled=True) | Q(manifest__agent__enabled__isnull=True)
        )
    )
    if identity is not None:
        version = candidates.filter(pk=identity).first()
    elif identifier:
        local = candidates.filter(algorithm__identifier=identifier)
        version = local.order_by("-algorithm__project_tag_id", "-pk").first()
    else:
        version = None
    if version is None or not services.agent_algorithm_allowed(version):
        raise ComputeError("请从项目算子清单选择可执行的发布版本", 404)
    return version


def compute_tool(
    session, user, policy, name, args, *, turn_id, fingerprint, approval_digest=None
):
    from apps.compute.access import permission, require_actor
    from apps.compute import operator_copies
    from .compute_result_tools import _read_output
    from .compute_tools import compact_task

    if name == "prepare_research_geology_changes":
        from .hermes_geology import saved_decisions

        task = session_task(session, user, policy, args["checkTaskId"])
        return saved_decisions(session, user, task, args["actions"], approval_digest)
    if name == "list_research_geology_rules":
        return {
            "items": [
                {
                    "resourceId": row.pk,
                    "name": row.name,
                    "description": row.description[:200],
                }
                for row in geology_rule_sources(user, policy).order_by(
                    "-updated_at", "-pk"
                )[:15]
            ]
        }
    if name == "inspect_research_operator":
        task_id = args.get("taskId")
        task = session_task(session, user, policy, task_id) if task_id else None
        version = (
            task.version
            if task
            else published_version(args.get("versionId"), args.get("identifier"))
        )
        snapshot = task.operator_copy if task else None
        filename = args.get("file")
        if filename:
            require_actor(user, session.project_tag_id, "download_algorithm")
            return operator_copies.inspect_source(
                version, filename, args.get("offset", 0), snapshot=snapshot
            )
        result = {
            "versionId": version.pk,
            "identifier": version.algorithm.identifier,
            "version": version.version,
            "manifest": {
                key: version.manifest[key]
                for key in (
                    "schemaVersion",
                    "runtime",
                    "inputs",
                    "parameters",
                    "outputs",
                    "inputScriptBridge",
                )
                if key in version.manifest
            },
        }
        if permission(user, "download_algorithm"):
            result.update(operator_copies.inspect_source(version, snapshot=snapshot))
        return result
    if name == "submit_research_compute":
        version = published_version(args["versionId"])
        bindings, _, _ = services.expand_bindings(version.manifest, args["inputs"])
        for key, identity in bindings.items():
            if type(identity) is not int or identity < 1:
                raise ComputeError("请为算子输入提供有效的资源编号")
            resolve_input(session, user, policy, version, key, identity)
        edits = args.get("operatorEdits")
        source_task = args.get("retryOf")
        retry_of = (
            session_task(session, user, policy, source_task) if source_task else None
        )
        snapshot = (
            retry_of.operator_copy
            if retry_of and retry_of.version_id == version.pk
            else {}
        )
        reuse_id = args.get("reuseOperatorCopyFrom")
        if edits or snapshot or reuse_id:
            require_actor(user, session.project_tag_id, "download_algorithm")
            inherited = snapshot.get("edits", [])
            if reuse_id:
                seed = session_task(session, user, policy, reuse_id)
                inherited = seed.operator_copy.get("edits", [])
                if not inherited:
                    raise ComputeError("请选择已生成算子副本的任务")
            if edits or reuse_id:
                snapshot = operator_copies.prepare(
                    version, [*inherited, *(edits or [])]
                )
        digest = hashlib.sha256(f"{turn_id}:{fingerprint}".encode()).hexdigest()[:40]
        task = services.submit(
            user,
            {"parameters": {}, **args, "idempotencyKey": task_prefix(session) + digest},
            retry_of=retry_of,
            operator_copy=snapshot,
        )
        return {
            "taskId": str(task.pk),
            "versionId": task.version_id,
            "name": task.name,
            "status": task.status,
            **(
                {
                    "operatorCopy": {
                        "sourceSha256": snapshot["sourceSha256"],
                        "files": snapshot["files"],
                    }
                }
                if snapshot
                else {}
            ),
        }
    if name == "get_research_compute":
        task = session_task(session, user, policy, args["taskId"])
        deadline = monotonic() + args.get("waitSeconds", 0)
        while task.status in services.ACTIVE and monotonic() < deadline:
            sleep(min(0.5, max(0, deadline - monotonic())))
            task.refresh_from_db()
        if args.get("waitSeconds"):
            task = session_task(session, user, policy, task.pk)
        result = compact_task(task)
        result.pop("detail", None)
        result["outputs"] = [
            {
                key: output[key]
                for key in (
                    "id",
                    "key",
                    "label",
                    "kind",
                    "expired",
                    "importStatus",
                    "resourceId",
                    "downloadUrl",
                    "previewUrl",
                    "mapUrl",
                )
            }
            for output in result["outputs"]
        ]
        if task.failure:
            result["failure"] = task.failure
        if task.operator_copy:
            result["operatorCopy"] = {
                key: task.operator_copy[key] for key in ("sourceSha256", "files")
            }
        return result
    output = (
        ComputeOutput.objects.select_related("task__project_tag")
        .filter(
            pk=args["outputId"],
            task__owner=user,
            task__idempotency_key__startswith=task_prefix(session),
        )
        .first()
    )
    if output is None:
        raise ComputeError("请选择本会话中的计算成果", 404)
    task = session_task(session, user, policy, output.task_id)
    if args.get("taskId") and args["taskId"].casefold() != str(task.pk):
        raise ComputeError("请选择该计算任务实际返回的成果编号", 404)
    if name == "register_research_output":
        record = services.request_output_import(
            user, output, args.get("name", ""), request_source=f"hermes:{session.pk}"
        )
        return {
            "taskId": str(task.pk),
            "outputId": output.pk,
            "importId": record.pk,
            "status": record.status,
            "resourceId": record.resource_id,
        }
    return _read_output(
        output, task, args.get("offset", 0), args.get("limit", 30), concise=True
    )
