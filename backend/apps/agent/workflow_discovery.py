"""Read-only search available to workflow actors at each model decision."""

from copy import deepcopy
from hashlib import sha256
import json

from django.core.exceptions import PermissionDenied, ValidationError

from apps.projects.context import selected_project_id

from .capability_catalog import contracts, enabled
from .policy import fresh_user, require_access
from .selections import algorithm_ids, knowledge_domains
from .tool_contract_runtime import validate_arguments

TOOLS = (
    "search_tools",
    "search_knowledge",
    "read_knowledge_document",
    "search_resources",
    "list_compute_algorithms",
)
MAX_LOOKUPS = 4
GUIDANCE = (
    "\n如需补充依据，discovery.tools列出本环节可调用的检索。可先返回一个"
    '{"action":"工具名","arguments":{...}}，收到结果后再按本环节原格式交付。'
    "用研究对象、资料名称或待判断的标准组织检索词，核对来源和适用范围。"
    "目录命中可用于说明或提出方案，当前节点可执行动作见本环节合同。"
    "计算输入及参数按本节点的有效绑定和已批准范围提交。"
)


class WorkflowDiscovery:
    def __init__(self, workflow, *, allowed=True, source_run=None):
        self.workflow = workflow
        self.observations = []
        self.knowledge = []
        self.resources = set()
        self.requests = set()
        self.allowed = allowed
        self.source_run_id = source_run.pk if source_run else None
        self.bind = workflow.parameters.get("_businessFlow", {})

    def actor(self, policy=None):
        from apps.business_flows.state import parent_run
        from .models import AgentRun

        workflow = self.workflow
        if workflow.project_tag_id != selected_project_id():
            raise PermissionDenied("工具调用不属于当前项目")
        user = fresh_user(workflow.owner_id)
        if policy is None:
            policy = require_access(user, "agent", workflow.model)
        if self.bind:
            run = parent_run(workflow)
        elif self.source_run_id:
            run = AgentRun.objects.filter(
                pk=self.source_run_id,
                owner=user,
                project_tag_id=workflow.project_tag_id,
                model=workflow.model,
                cancel_requested=False,
            ).first()
            if run is None:
                raise PermissionDenied("来源对话已停止或归属已变化")
        else:
            run = (
                None
                if workflow._state.adding
                else workflow.chat_runs.filter(
                    owner=user, project_tag_id=workflow.project_tag_id
                )
                .order_by("id")
                .first()
            )
            if run is None:
                run = AgentRun(
                    owner=user,
                    project_tag_id=workflow.project_tag_id,
                    model=workflow.model,
                    prompt=workflow.goal,
                    knowledge_selection={
                        **workflow.plan.get("knowledgeSelection", {}),
                        "_resolvedDomains": knowledge_domains_for_goal(workflow.goal),
                    },
                )
        return user, policy, run

    def packet(self, policy=None):
        if not self.allowed or (
            self.bind
            and (self.bind.get("agentEnabled") is False or not self.bind.get("runId"))
        ):
            return {}
        user, policy, run = self.actor(policy)
        tools = {
            name: contracts()[name]["inputSchema"]
            for name in TOOLS
            if len(self.observations) < MAX_LOOKUPS
            and enabled(name, user, policy, run=run)
        }
        questions = (
            self.bind.get("definitionSnapshot", {})
            .get("skill", {})
            .get("knowledgeQuestions", [])
            if "search_knowledge" in tools
            else []
        )
        return {
            "tools": tools,
            "remainingLookups": MAX_LOOKUPS - len(self.observations),
            "knowledgeQuestions": questions,
            "observations": deepcopy(self.observations),
        }

    def parse(self, raw, allowed):
        if not allowed or not raw.lstrip().startswith("{"):
            return None
        # Match the exact single-tool envelope. Other stage responses still go
        # through their original result/decision validation.
        from .business_flow_actions import _read_json

        try:
            value = _read_json(raw)
        except (ValueError, TypeError, RecursionError):
            return None
        if (
            isinstance(value, dict)
            and set(value) == {"action", "arguments"}
            and isinstance(value["action"], str)
            and value["action"] in TOOLS
        ):
            if value["action"] not in allowed:
                raise PermissionDenied("当前环节无权调用此检索工具")
            return value
        return None

    def lookup(self, action, guard):
        from apps.business_flows import knowledge
        from .tools import _execute_authorized, execute

        guard()
        name, args = action["action"], deepcopy(action["arguments"])
        user, policy, run = self.actor()
        if len(self.observations) >= MAX_LOOKUPS or not enabled(
            name, user, policy, run=run
        ):
            raise PermissionDenied("当前检索次数或工具权限已变化")
        status = "matched"
        try:
            validate_arguments(name, args)
            identity = sha256(
                json.dumps([name, args], ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest()
            if identity in self.requests:
                raise ValidationError("已有相同检索结果，可换用检索词或翻页")
            self.requests.add(identity)
            if name == "search_resources":
                args.setdefault("category", "uploaded_data")
                args["limit"] = min(args.get("limit", 5), 5)
            elif name == "read_knowledge_document":
                args["limit"] = min(args.get("limit", 1500), 1500)

            if run.pk:
                result, pairs = execute(run, name, args, workflow_catalog=True)
            else:
                result, pairs = _execute_authorized(
                    run, name, args, user, policy, None, workflow_catalog=True
                )
            guard()

            if name in knowledge.TOOLS:
                pairs = [pair for pair in pairs if pair[1].get("items")][:2] + [
                    pair for pair in pairs if pair[1].get("documents")
                ][:1]
                entries = knowledge.retain(run, name, pairs) if self.bind else []
                for _, part in pairs:
                    self.knowledge.append(
                        (
                            name,
                            {
                                "items": [
                                    {key: item[key] for key in ("id", "revision")}
                                    for item in part.get("items", [])
                                ],
                                "documents": [
                                    {
                                        key: item[key]
                                        for key in ("documentId", "documentSha256")
                                    }
                                    for item in part.get("documents", [])
                                ],
                            },
                        )
                    )
                items = []
                for _, part in pairs:
                    item = (part.get("items") or part["documents"])[0]
                    row = {
                        key: item[key]
                        for key in (
                            "id",
                            "revision",
                            "documentId",
                            "documentSha256",
                            "title",
                            "sourceUrl",
                            "chunkId",
                            "nextOffset",
                            "domain",
                        )
                        if key in item
                    }
                    row["excerpt"] = str(
                        item.get("statement") or item.get("content") or ""
                    )[:1500]
                    for key in ("conditions", "exceptions", "sources"):
                        if item.get(key):
                            row[key] = [str(value)[:120] for value in item[key][:3]]
                    if entries:
                        row["evidenceId"] = f"knowledge-{entries[len(items)]['id']}"
                    items.append(row)
                status = (
                    "matched"
                    if items
                    else "empty"
                    if result.get("documentSearch", {}).get("available")
                    else "documents_unavailable"
                )
                result = {"items": items}
            elif name == "search_resources":
                items = [
                    {
                        "id": row["id"],
                        "name": row["name"][:160],
                        "dataType": row["dataType"],
                        "origin": row["origin"],
                        "description": row["description"][:160],
                    }
                    for row in result["items"]
                ]
                self.resources.update(row["id"] for row in items)
                result = {
                    **{k: result[k] for k in ("total", "nextOffset")},
                    "items": items,
                }
        except ValidationError as error:
            status, result = (
                "invalid_query",
                {"detail": "; ".join(error.messages)[:250]},
            )

        self.observations.append({"tool": name, "status": status, "result": result})
        return {"tool": name, "status": status, "count": len(result.get("items", []))}

    def snapshot(self):
        return {
            "observations": deepcopy(self.observations),
            "knowledge": deepcopy(self.knowledge),
            "resources": sorted(self.resources),
            "requests": sorted(self.requests),
        }

    def restore(self, snapshot):
        self.observations = deepcopy(snapshot.get("observations", []))
        self.knowledge = deepcopy(snapshot.get("knowledge", []))
        self.resources = set(snapshot.get("resources", []))
        self.requests = set(snapshot.get("requests", []))
        self.authorize()

    def authorize(self):
        if not self.knowledge and not self.resources:
            return
        from .knowledge_tools import check_knowledge_evidence
        from .resource_discovery import discover_resources

        user, policy, run = self.actor()
        if self.resources:
            visible = set(
                discover_resources(user, policy, self.resources).values_list(
                    "pk", flat=True
                )
            )
            if visible != self.resources:
                raise PermissionDenied("检索数据已撤权或不属于当前项目")
        if self.knowledge:
            if not policy["allowDocuments"] and any(
                result["documents"] for _, result in self.knowledge
            ):
                raise PermissionDenied("文档读取权限已关闭")
            if any(
                not enabled(tool, user, policy, run=run) for tool, _ in self.knowledge
            ):
                raise PermissionDenied("知识工具访问权限已变化")
            check_knowledge_evidence(
                user,
                {
                    (item["id"], item["revision"])
                    for _, result in self.knowledge
                    for item in result.get("items", [])
                },
                {
                    (item["documentId"], item["documentSha256"])
                    for _, result in self.knowledge
                    for item in result.get("documents", [])
                },
                domains=knowledge_domains(run),
            )


def knowledge_domains_for_goal(goal):
    from apps.knowledge.domains import DOMAINS, query_domains

    return query_domains(goal) or list(DOMAINS)


def compact_algorithms(user, query, run):
    from .tools import _algorithm_list

    result = _algorithm_list(user, query, version_ids=algorithm_ids(run))
    return {
        "items": [
            {
                "name": row["name"][:120],
                "identifier": row["identifier"],
                "description": row["description"][:180],
                "versions": [
                    {"id": version["id"], "version": version["version"]}
                    for version in row["versions"][:3]
                ],
            }
            for row in result["items"][:6]
        ],
        "truncated": result["truncated"] or len(result["items"]) > 6,
    }
