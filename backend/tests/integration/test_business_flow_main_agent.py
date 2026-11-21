"""One executor survives milestones, human waiting and subsequent skill releases."""

from copy import deepcopy
import json
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from apps.agent import provider
from apps.agent.models import AgentToolCall

from apps.business_flows import catalog, engine, runtime
from apps.business_flows.builtins import source_summary_definition
from apps.business_flows.state import parent_run, state
from apps.business_flows.node_trace import node_trace
from apps.projects.context import project_scope
from apps.projects.models import Project
from apps.knowledge.models import KnowledgeEntry
from tests.integration.test_business_flow_runtime import flows  # noqa: F401
from tests.integration.test_agent import setup_agent  # noqa: F401

# ruff: noqa: F811
pytestmark = pytest.mark.efficiency


def install_model(monkeypatch):
    calls = []
    monkeypatch.setattr(provider, "model_window", lambda *_: 32768)
    monkeypatch.setattr(provider, "count_tokens", lambda *_args, **_kw: 1000)

    def response(model, messages, maximum, guard, **options):
        guard()
        packet = json.loads(messages[1]["content"])
        calls.append({"packet": packet, "messages": deepcopy(messages)})
        if "nodeContext" in packet:
            context = packet["nodeContext"]
            phase = context["task"]["phase"]
            if phase == "select_node":
                result = {
                    "action": "start_node",
                    "arguments": {"nodeId": context["task"]["readyNodes"][-1]["id"]},
                }
            elif phase == "finish_workflow":
                result = {
                    "action": "finish_workflow",
                    "arguments": {"summary": "已完成任务及真实成果核查"},
                }
            else:
                refs = [row["id"] for row in packet["evidence"]]
                contract = context["contract"]
                result = {
                    "action": "finish_node",
                    "arguments": {
                        "summary": "依据实际资料形成有来源的分析",
                        "outputs": [
                            {**row, "evidenceId": refs[0]}
                            for row in contract["requiredOutputs"]
                        ],
                        "evidenceIds": refs,
                        "limitations": [],
                        "acceptanceChecks": contract["acceptance"],
                    },
                }
        else:
            result = {
                "decision": "accept",
                "reason": "当前实际证据支持结果",
                "evidenceIds": [row["id"] for row in packet["evidence"]],
            }
        yield json.dumps(result, ensure_ascii=False)

    monkeypatch.setattr(provider, "stream", response)
    monkeypatch.setattr(
        "apps.agent.business_flow_actions.request_action",
        lambda *_a, **_k: pytest.fail("任务主循环不得调用节点执行智能体"),
    )
    monkeypatch.setattr(
        "apps.agent.business_flow_execution.execute_node",
        lambda *_a, **_k: pytest.fail("任务主循环不得派生节点分析智能体"),
    )
    return calls


@pytest.mark.parametrize("published", [True, False])
def test_main_agent_searches_authored_questions_and_rechecks_sources(
    flows, monkeypatch, published
):
    env = flows
    calls = install_model(monkeypatch)
    original = provider.stream
    question = "构造判读需要核对哪些比例尺和区域适用条件？"
    query = "地质 构造判读 比例尺"

    def response(model, messages, maximum, guard, **options):
        packet = json.loads(messages[1]["content"])
        discovery = packet.get("discovery", {})
        if (
            discovery.get("knowledgeQuestions")
            and not discovery.get("observations")
            and not any(
                call.get("packet", {}).get("discovery", {}).get("observations")
                for call in calls
            )
        ):
            assert discovery["knowledgeQuestions"] == [question]
            assert "search_knowledge" in discovery["tools"]
            guard()
            yield json.dumps(
                {"action": "search_knowledge", "arguments": {"query": query}}
            )
            return
        yield from original(model, messages, maximum, guard, **options)

    monkeypatch.setattr(provider, "stream", response)
    monkeypatch.setattr(
        "apps.knowledge.library.search_documents",
        lambda *_args, **_kwargs: {"items": [], "available": True, "detail": ""},
    )
    other_project = Project.objects.create(code="knowledge-other", name="另一项目")
    KnowledgeEntry._base_manager.create(
        project_tag_id=other_project.pk,
        title="其他项目构造判读比例尺",
        subject="构造判读",
        statement="其他项目专用知识",
        status="published",
    )
    with project_scope(env["scope"]):
        entry = KnowledgeEntry.objects.create(
            title="本区构造判读比例尺",
            subject="构造判读",
            statement="应同时核对实际制图比例尺与观测分辨率。",
            status="published" if published else "draft",
        )
        definition = source_summary_definition(main_agent=True)
        definition["skill"]["knowledgeQuestions"] = [question]
        _, version = catalog.register_flow(
            env["admin"],
            {
                "code": "knowledge-test",
                "name": "知识依据核对",
                "definition": definition,
            },
        )
        workflow = runtime.start_flow(
            env["user"],
            version,
            {
                "model": "mock",
                "goal": "核对项目资料中的地质构造判读口径",
                "inputs": {"source": env["resource"].pk},
                "idempotencyKey": uuid4().hex,
            },
        )
        for _ in range(16):
            engine.advance(workflow.pk)
            workflow.refresh_from_db()
            if workflow.status == "succeeded":
                break
        assert workflow.status == "succeeded", workflow.detail
        run = parent_run(workflow)
        assert run.knowledge_selection["mode"] == "auto"
        assert (
            AgentToolCall.objects.filter(
                run=run, tool="search_knowledge", status="succeeded"
            ).count()
            == 1
        )
        evidence = [row for row in run.evidence if row["tool"] == "search_knowledge"]
        assert [row["result"]["items"][0]["id"] for row in evidence] == (
            [entry.pk] if published else []
        )
        observation = next(
            observation
            for call in calls
            for observation in call["packet"]
            .get("discovery", {})
            .get("observations", [])
        )
        assert observation["status"] == ("matched" if published else "empty")
        assert (
            any(
                row["kind"] == "knowledge"
                and row["result"]["revision"] == entry.revision
                for call in calls
                for row in call["packet"]["evidence"]
            )
            is published
        )
        if published:
            entry.status = "draft"
            entry.save(update_fields=["status"])
            with pytest.raises(PermissionDenied, match="知识依据"):
                runtime.authorize(env["user"], workflow, history=True)


def test_base_discovery_at_all_main_agent_decisions_without_authored_questions(
    flows, monkeypatch, settings
):
    from apps.catalog.models import DataResource

    env = flows
    settings.WEKNORA_CONFIG = {}
    install_model(monkeypatch)
    original = provider.stream
    actions = {
        "select_node": ("search_tools", {"query": "search_resources"}),
        "work": ("search_resources", {"query": "补充样地"}),
        "reviewer": ("search_knowledge", {"query": "适用尺度"}),
        "finish_workflow": ("search_resources", {"query": "补充样地"}),
    }
    completed = {}

    def response(model, messages, maximum, guard, **options):
        packet = json.loads(messages[1]["content"])
        context = packet.get("nodeContext", {})
        phase = context.get("task", {}).get("phase", "reviewer")
        search = packet["discovery"]
        assert not search["knowledgeQuestions"]
        assert set(search["tools"]) >= {
            "search_tools",
            "search_knowledge",
            "read_knowledge_document",
            "search_resources",
        }
        if phase not in completed:
            if not search["observations"]:
                name, args = actions[phase]
                yield json.dumps(
                    {"action": name, "arguments": args}, ensure_ascii=False
                )
                return
            completed[phase] = search["observations"][0]["result"]["items"]
        yield from original(model, messages, maximum, guard, **options)

    monkeypatch.setattr(provider, "stream", response)
    definition = source_summary_definition(main_agent=True)
    definition["skill"].pop("knowledgeQuestions")
    definition["nodes"][0]["review"].update(ai=True, maxRevisions=1)
    for pid in (1, env["project"].pk):
        DataResource._base_manager.create(
            project_tag_id=pid,
            code=f"extra-samples-{pid}",
            name=f"补充样地 {pid}",
            data_type="table",
            file_format="SQLITE",
            storage_path="samples",
        )
        KnowledgeEntry._base_manager.create(
            project_tag_id=pid,
            title=f"样地适用尺度 {pid}",
            subject="适用尺度",
            statement="适用尺度取决于实际采样间距。",
            status="published",
        )
    with project_scope(env["scope"]):
        _, version = catalog.register_flow(
            env["admin"],
            {
                "code": "flow-discovery",
                "name": "科研资料检索",
                "definition": definition,
            },
        )
        workflow = runtime.start_flow(
            env["user"],
            version,
            {
                "model": "mock",
                "goal": "核对实际样地的适用尺度",
                "inputs": {"source": env["resource"].pk},
                "idempotencyKey": uuid4().hex,
            },
        )
        for _ in range(14):
            engine.advance(workflow.pk)
            workflow.refresh_from_db()
            if workflow.status == "succeeded":
                break
        assert workflow.status == "succeeded", workflow.detail
        assert set(completed) == set(actions)
        assert [row["name"] for row in completed["select_node"]] == ["search_resources"]
        for phase in ("work", "finish_workflow"):
            assert [row["name"] for row in completed[phase]] == [
                f"补充样地 {env['project'].pk}"
            ]
        assert [row["title"] for row in completed["reviewer"]] == [
            f"样地适用尺度 {env['project'].pk}"
        ]
        assert parent_run(workflow).resource_ids == [env["resource"].pk]
        assert (
            AgentToolCall.objects.filter(
                run=parent_run(workflow), status="succeeded"
            ).count()
            == 4
        )


def test_executor_continues_after_human_wait_with_frozen_skill(flows, monkeypatch):
    env = flows
    calls = install_model(monkeypatch)
    definition = source_summary_definition(main_agent=True)
    definition["skill"]["instructions"] = "依据实际资料逐节点梳理，保留引用与局限。"
    definition["nodes"][0]["review"].update(ai=True, human=True, maxRevisions=1)
    definition["nodes"][1].update(
        kind="agent", instruction="依据前序已核验结果完成综合说明。"
    )
    with project_scope(env["scope"]):
        flow, version = catalog.register_flow(
            env["admin"],
            {
                "code": "main-" + uuid4().hex[:8],
                "name": "持续执行验收",
                "definition": definition,
            },
        )
        workflow = runtime.start_flow(
            env["user"],
            version,
            {
                "model": "mock",
                "goal": "逐步解释真实资料并复核",
                "inputs": {"source": env["resource"].pk},
                "idempotencyKey": uuid4().hex,
            },
        )
        identity = runtime.serialize_run(env["user"], workflow)["mainAgent"]["id"]
        engine.advance(workflow.pk)
        workflow.refresh_from_db()
        assert (
            workflow.parameters["_businessFlow"]["executorSession"]["loop"][
                "activeNodeId"
            ]
            == "summarize"
        )
        runtime.control_flow(env["user"], workflow, "pause")
        workflow.refresh_from_db()
        before = len(calls)
        engine.advance(workflow.pk)
        assert len(calls) == before
        runtime.control_flow(env["user"], workflow, "resume")
        workflow.refresh_from_db()
        for _ in range(8):
            engine.advance(workflow.pk)
            workflow.refresh_from_db()
            if workflow.status == "waiting_approval":
                break
        assert workflow.status == "waiting_approval", workflow.detail
        changed = deepcopy(definition)
        changed["skill"]["instructions"] = (
            "仅用于后来新任务的技能，不能覆盖运行中任务。"
        )
        _, newer = catalog.publish_version(env["admin"], flow, changed)
        assert newer.pk != version.pk
        runtime.decide_flow(
            env["user"],
            workflow,
            {
                "nodeId": "summarize",
                "revision": state(workflow)["revision"],
                "decision": "approve",
                "idempotencyKey": uuid4().hex,
            },
        )
        for _ in range(12):
            engine.advance(workflow.pk)
            workflow.refresh_from_db()
            if workflow.status == "succeeded":
                break
        assert workflow.status == "succeeded", workflow.detail
        assert (
            runtime.serialize_run(env["user"], workflow)["mainAgent"]["id"] == identity
        )
        assert state(workflow)["ledger"]["entries"][0]["summary"]
        root_trace = node_trace(env["user"], workflow, "_main")
        assert all(
            row["role"] == "executor" and row["executorSessionId"] == identity
            for row in root_trace["requests"]
        )
        assert any(row["nodeId"] == "_main" for row in root_trace["requests"])
    assert {row["packet"]["executionSession"]["id"] for row in calls} == {identity}
    assert {row["packet"]["executionSession"]["actor"] for row in calls} == {
        "main_executor",
        "independent_reviewer",
    }
    assert all("后来新任务" not in row["messages"][0]["content"] for row in calls)
    records = list(
        workflow.steps.filter(kind="model_activity", action__actor="executor")
    )
    assert len(records) >= 2
    assert {row.action["executorSessionId"] for row in records} == {identity}


def test_main_executor_selects_legal_milestones_and_rejects_future_nodes(
    flows, monkeypatch
):
    calls = install_model(monkeypatch)
    definition = source_summary_definition(main_agent=True)
    a = deepcopy(definition["nodes"][0])
    a["id"] = "first"
    b = deepcopy(a)
    b["id"] = "second"
    finish = definition["nodes"][1]
    finish["dependsOn"] = ["first", "second"]
    definition["nodes"] = [a, b, finish]
    with project_scope(flows["scope"]):
        _, version = catalog.register_flow(
            flows["admin"],
            {
                "code": "route-" + uuid4().hex[:8],
                "name": "主执行路由验证",
                "definition": definition,
            },
        )
        workflow = runtime.start_flow(
            flows["user"],
            version,
            {
                "model": "mock",
                "goal": "完成全部目标",
                "inputs": {"source": flows["resource"].pk},
                "idempotencyKey": uuid4().hex,
            },
        )
        for _ in range(20):
            engine.advance(workflow.pk)
            workflow.refresh_from_db()
            if workflow.status == "succeeded":
                break
        assert workflow.status == "succeeded", workflow.detail
    starts = [
        row["packet"]["nodeContext"]["task"]["readyNodes"][-1]["id"]
        for row in calls
        if row["packet"].get("nodeContext", {}).get("task", {}).get("phase")
        == "select_node"
    ]
    assert starts == ["second", "first", "finish"]
    assert (
        workflow.parameters["_businessFlow"]["executorSession"]["loop"]["completed"]
        is True
    )


def test_main_agent_question_resumes_an_implicit_contract_without_new_executor(
    flows, monkeypatch
):
    env = flows
    calls = install_model(monkeypatch)
    normal = provider.stream
    asked = False

    def stream(model, messages, maximum, guard, **options):
        nonlocal asked
        packet = json.loads(messages[1]["content"])
        if (
            packet.get("nodeContext", {}).get("task", {}).get("phase") == "work"
            and not asked
        ):
            asked = True
            guard()
            yield json.dumps(
                {"action": "ask_user", "arguments": {"question": "请确认资料范围"}}
            )
        else:
            yield from normal(model, messages, maximum, guard, **options)

    monkeypatch.setattr(provider, "stream", stream)
    with project_scope(env["scope"]):
        _, version = catalog.register_flow(
            env["admin"],
            {
                "code": "question-" + uuid4().hex[:8],
                "name": "主执行补充说明",
                "definition": source_summary_definition(main_agent=True),
            },
        )
        workflow = runtime.start_flow(
            env["user"],
            version,
            {
                "model": "mock",
                "goal": "理解资料并说明依据",
                "inputs": {"source": env["resource"].pk},
                "idempotencyKey": uuid4().hex,
            },
        )
        identity = workflow.parameters["_businessFlow"]["executorSession"]["id"]
        for _ in range(3):
            engine.advance(workflow.pk)
            workflow.refresh_from_db()
            if workflow.status == "waiting_approval":
                break
        assert workflow.status == "waiting_approval"
        workflow = runtime.decide_flow(
            env["user"],
            workflow,
            {
                "nodeId": "summarize",
                "decision": "retry_recovery",
                "feedback": "以本次绑定资料为准",
                "revision": state(workflow)["revision"],
                "idempotencyKey": uuid4().hex,
            },
        )
        for _ in range(12):
            engine.advance(workflow.pk)
            workflow.refresh_from_db()
            if workflow.status == "succeeded":
                break
        assert workflow.status == "succeeded", workflow.detail
        assert workflow.parameters["_businessFlow"]["executorSession"]["id"] == identity
        assert any(
            row["packet"].get("nodeContext", {}).get("userAnswer")
            == "以本次绑定资料为准"
            for row in calls
        )
