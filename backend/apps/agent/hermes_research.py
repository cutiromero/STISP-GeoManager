"""Research plans and compute tools for Hermes sessions."""

import hashlib
import json
from functools import lru_cache

from django.conf import settings
from django.core.exceptions import PermissionDenied

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


def workflow_plan(version_id):
    version = (
        BusinessFlowVersion._base_manager.select_related("flow")
        .filter(pk=version_id, status="published", flow__in=catalog_flows())
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
    return authorized_task(user, task_id, policy)


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


def compute_tool(session, user, policy, name, args, *, turn_id, fingerprint):
    from .compute_result_tools import _read_output
    from .compute_tools import compact_task
    from .resource_discovery import resolve_discoverable_resource

    if name == "submit_research_compute":
        version = AlgorithmVersion.objects.filter(
            pk=args["versionId"],
            status="published",
            algorithm__enabled=True,
            algorithm__in=services.allowed_algorithms(),
        ).first()
        if version is None or not services.agent_algorithm_allowed(version):
            raise ComputeError("请从项目算子清单选择可执行的发布版本", 404)
        bindings, _, _ = services.expand_bindings(version.manifest, args["inputs"])
        for identity in bindings.values():
            if type(identity) is not int or identity < 1:
                raise ComputeError("请为算子输入提供有效的资源编号")
        for identity in set(bindings.values()):
            resolve_discoverable_resource(user, policy, identity)
        digest = hashlib.sha256(f"{turn_id}:{fingerprint}".encode()).hexdigest()[:40]
        task = services.submit(
            user,
            {"parameters": {}, **args, "idempotencyKey": task_prefix(session) + digest},
        )
        return {
            "taskId": str(task.pk),
            "versionId": task.version_id,
            "name": task.name,
            "status": task.status,
        }
    if name == "get_research_compute":
        task = session_task(session, user, policy, args["taskId"])
        result = compact_task(task)
        result.pop("detail", None)
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
