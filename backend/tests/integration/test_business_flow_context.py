"""长度驱动桩覆盖证据引用、逐档整理、台账与可恢复等待。"""

from copy import deepcopy
import json
from uuid import uuid4

from django.core.exceptions import PermissionDenied
import pytest

from apps.agent import provider
from apps.agent.business_flow_context import (
    ContextReviewRequired,
    MAX_TOKEN_MEASUREMENTS,
    prepare_packet,
    project_evidence,
)
from apps.business_flows import catalog, engine, runtime
from apps.business_flows.builtins import source_summary_definition
from apps.business_flows.ledger import MAX_LEDGER_BYTES, complete_node, size
from apps.business_flows.state import state
from apps.compute.packages import ComputeError
from apps.projects.context import project_scope
from tests.integration.test_business_flow_runtime import flows, start, advance  # noqa: F401
from tests.integration.test_agent import setup_agent  # noqa: F401

# ruff: noqa: F811
pytestmark = pytest.mark.efficiency
TOKEN_DIVISOR = 4


def length_tokens(model, messages, *args):
    return (
        sum(len(message["content"]) for message in messages) + TOKEN_DIVISOR - 1
    ) // TOKEN_DIVISOR


def evidence(identity="source", result=None):
    return {
        "id": identity,
        "title": "资料" + identity,
        "kind": "resource",
        "result": result or {"count": 8},
    }


def packet(rows):
    return {
        "node": {"id": "analyse", "instruction": "依据实际证据分析"},
        "evidence": rows,
        "ledger": {"goal": "科研任务", "entries": [], "unresolved": []},
        "contextNotice": [],
    }


def prepare(monkeypatch, rows, budget, *, direct=(), tokens=None):
    measured, summaries = [], []

    def count(model, messages, *args):
        measured.append(deepcopy(messages))
        return (tokens or length_tokens)(model, messages, *args)

    def summarize(messages, batch, count, management):
        summaries.append(deepcopy(batch))
        return {
            row["id"]: "本批资料的受限摘要；未提供的内容不作为依据。" for row in batch
        }

    monkeypatch.setattr(provider, "count_tokens", count)
    result = prepare_packet(
        packet(rows),
        "依据真实资料输出",
        None,
        {
            "maxContextTokens": budget,
            "maxOutputTokens": 512,
            "maxContextBytes": 192 * 1024,
        },
        budget + 512 + 256,
        direct_ids=set(direct),
        summarize=summarize,
        checked=lambda: None,
    )
    return result, measured, summaries


def test_large_single_evidence_uses_level_one_with_exact_counts(monkeypatch):
    rows = [
        evidence(
            result={
                "sample": [{"value": str(index) + "x" * 80} for index in range(1240)],
                "fields": ["field-" + str(index) for index in range(100)],
                "groups": list(range(20)),
                "text": "长" * 5000,
            }
        )
    ]
    original = deepcopy(rows)
    (actual, _, audit), measured, summaries = prepare(monkeypatch, rows, 2500)
    assert audit["level"] == 1 and not summaries and len(measured) == 2
    assert rows == original
    changes = {row["path"]: row for row in actual["contextNotice"][0]["changes"]}
    assert (
        changes["result.sample"]["originalCount"],
        changes["result.sample"]["retainedCount"],
    ) == (1240, 10)
    assert changes["result.fields"]["retainedCount"] == 40
    assert changes["result.groups"]["retainedCount"] == 8
    assert "1240 → 10" in audit["noticeSummary"][0]
    assert (
        changes["result.text"]["retainedCount"]
        == len(actual["evidence"][0]["result"]["text"])
        == 1000
    )
    assert actual["contextNotice"][0]["originalBytes"] == len(
        json.dumps(rows[0], ensure_ascii=False, separators=(",", ":")).encode()
    )


def test_many_items_use_level_two_and_keep_ids_titles(monkeypatch):
    count, budget = 30, 3500
    rows = [evidence(f"source-{index}", {"value": "x" * 900}) for index in range(count)]
    (actual, _, audit), measured, summaries = prepare(monkeypatch, rows, budget)
    assert audit["level"] == 2 and not summaries
    assert len(measured) <= 3
    assert {row["id"] for row in actual["evidence"]} == {row["id"] for row in rows}
    assert all(
        set(row) == {"id", "title", "kind", "summary"} for row in actual["evidence"]
    )
    assert len(actual["contextNotice"]) == count
    assert all(
        row["action"] == "index_summary" and row["originalBytes"] > row["retainedBytes"]
        for row in actual["contextNotice"]
    )


def test_direct_dependency_requires_bounded_batch_summaries(monkeypatch):
    rows = [evidence(f"source-{index}", {"value": "x" * 900}) for index in range(12)]
    first, measured, batches = prepare(
        monkeypatch, rows, 1800, direct=[row["id"] for row in rows]
    )
    second, _, _ = prepare(monkeypatch, rows, 1800, direct=[row["id"] for row in rows])
    actual, _, audit = first
    assert first == second
    assert audit["level"] == 3 and len(batches) == 2
    assert len(measured) <= MAX_TOKEN_MEASUREMENTS
    assert len({json.dumps(value, ensure_ascii=False) for value in measured}) == len(
        measured
    )
    assert [row["evidenceId"] for row in actual["contextNotice"]] == [
        row["id"] for row in rows
    ]
    assert all(row["action"] == "batch_summary" for row in actual["contextNotice"])


def test_all_levels_too_large_have_bounded_tokenizer_calls(monkeypatch):
    measured = []
    monkeypatch.setattr(
        provider, "count_tokens", lambda *args: measured.append(args) or 1000000
    )
    with pytest.raises(ContextReviewRequired) as caught:
        prepare_packet(
            packet([evidence()]),
            "分析",
            None,
            {
                "maxContextTokens": 1000,
                "maxOutputTokens": 512,
                "maxContextBytes": 192 * 1024,
            },
            1768,
            direct_ids=set(),
            summarize=lambda *args: pytest.fail("不应发送超预算批次"),
            checked=lambda: None,
        )
    assert caught.value.details["level"] == 3
    assert len(measured) <= MAX_TOKEN_MEASUREMENTS


def install_model(monkeypatch, *, window=32768, tokenizer=length_tokens):
    calls = []
    monkeypatch.setattr(provider, "model_window", lambda model: window)
    monkeypatch.setattr(provider, "count_tokens", tokenizer)

    def stream(model, messages, maximum, guard, **options):
        guard.poll()
        payload = json.loads(messages[1]["content"])
        calls.append(
            {
                "packet": deepcopy(payload),
                "messages": deepcopy(messages),
                "maximum": maximum,
            }
        )
        options["on_usage"](
            {
                "prompt_tokens": length_tokens(model, messages),
                "completion_tokens": 20,
                "total_tokens": length_tokens(model, messages) + 20,
            }
        )
        identities = [row["id"] for row in payload["evidence"]]
        if messages[0]["content"].startswith("你只整理资料"):
            result = {
                "evidence": [
                    {"id": identity, "summary": "本批资料的有界要点，未读取省略内容。"}
                    for identity in identities
                ]
            }
        elif "decision,reason,issues" in messages[0]["content"]:
            result = {
                "decision": "accept",
                "reason": "核对实际输入与已说明的省略后通过",
                "issues": [],
                "repairInstructions": "",
                "evidenceIds": identities,
            }
        else:
            result = {
                "summary": "当前节点依据实际资料得到结论",
                "findings": ["该节点完成受控分析"],
                "limitations": [],
                "evidenceIds": identities,
            }
        yield json.dumps(result, ensure_ascii=False)

    monkeypatch.setattr(provider, "stream", stream)
    return calls


def test_five_node_chain_stops_raw_ancestor_propagation_and_measures_sizes(
    flows, monkeypatch
):
    spec = source_summary_definition()
    template = spec["nodes"][0]
    spec["nodes"] = [
        {
            **deepcopy(template),
            "id": f"node{index}",
            "title": f"节点{index}",
            "dataRoles": ["source"] if index <= 2 else [],
            "dependsOn": [f"node{index - 1}"] if index > 1 else [],
        }
        for index in range(1, 6)
    ]
    with project_scope(flows["scope"]):
        _, version = catalog.register_flow(
            flows["admin"],
            {
                "code": "chain-" + uuid4().hex[:8],
                "name": "五节点链",
                "description": "引用传递",
                "definition": spec,
            },
        )
    calls = install_model(monkeypatch)
    original_inputs = engine.input_evidence
    raw = [
        evidence(
            f"ancestor-raw-{index}", {"raw": f"PRIVATE-RAW-{index}-" + "x" * 12000}
        )
        for index in range(1, 3)
    ]

    def inputs(workflow, user, policy, node):
        result = original_inputs(workflow, user, policy, node)
        return [
            *result,
            *(
                [raw[int(node["id"][-1]) - 1]]
                if node["id"] in {"node1", "node2"}
                else []
            ),
        ]

    monkeypatch.setattr(engine, "input_evidence", inputs)
    workflow, _ = start(flows, version)
    for _ in range(5):
        advance(flows, workflow)
    final = calls[-1]["packet"]
    assert [row["id"] for row in final["evidence"]] == ["node-node4"]
    assert "PRIVATE-RAW-1" not in json.dumps(
        final
    ) and "PRIVATE-RAW-2" not in json.dumps(final)
    assert [row["nodeId"] for row in final["ledger"]["entries"]] == [
        "node1",
        "node2",
        "node3",
        "node4",
    ]
    assert final["ledger"]["entries"][0]["sources"], final["ledger"]["entries"][0]
    old_outputs, old_results = {}, {}
    for index, call in enumerate(calls, start=1):
        own = (
            [row for row in call["packet"]["evidence"] if row["kind"] == "resource"]
            if index <= 2
            else []
        )
        inherited = (
            [
                *old_outputs[index - 1],
                {
                    "id": f"node-node{index - 1}",
                    "kind": "analysis",
                    "title": f"node{index - 1}",
                    "result": old_results[index - 1],
                },
            ]
            if index > 1
            else []
        )
        old_outputs[index] = list(
            {row["id"]: deepcopy(row) for row in [*own, *inherited]}.values()
        )
        old_results[index] = {
            "summary": "当前节点依据实际资料得到结论",
            "findings": ["该节点完成受控分析"],
            "limitations": [],
            "evidenceIds": [row["id"] for row in old_outputs[index]],
        }
    old = {
        key: deepcopy(value)
        for key, value in final.items()
        if key not in {"ledger", "contextNotice"}
    }
    old["evidence"] = old_outputs[5]
    metrics = {
        "before": {
            "bytes": size(old),
            "stubTokens": length_tokens(
                None,
                [
                    {
                        "content": json.dumps(
                            old, ensure_ascii=False, separators=(",", ":")
                        )
                    }
                ],
            ),
        },
        "after": {
            "bytes": size(final),
            "stubTokens": length_tokens(
                None,
                [
                    {
                        "content": json.dumps(
                            final, ensure_ascii=False, separators=(",", ":")
                        )
                    }
                ],
            ),
        },
    }
    assert metrics["before"]["bytes"] > metrics["after"]["bytes"]
    print("FIVE_NODE_PACKET_METRICS=" + json.dumps(metrics))
    with project_scope(flows["scope"]):
        public = runtime.serialize_run(flows["user"], workflow)
        assert "contextSnapshots" not in json.dumps(
            public
        ) and "executionContextId" not in json.dumps(public)


def test_review_receives_exact_execution_projection_and_notices(flows, monkeypatch):
    _, version = flows["create"](one=True, ai=True)
    calls = install_model(monkeypatch, window=12500)
    monkeypatch.setattr(
        engine,
        "input_evidence",
        lambda *args: [
            evidence(result={"rows": list(range(1240)), "text": "x" * 24000})
        ],
    )
    workflow, _ = start(flows, version)
    result = advance(flows, workflow)
    assert result["status"] == "queued", workflow.detail
    assert len(calls) == 2
    execution, review = [row["packet"] for row in calls]
    assert review["evidence"][:-1] == execution["evidence"]
    assert review["evidence"][-1]["id"] == "execution-result"
    assert review["contextNotice"] == execution["contextNotice"]
    assert result["nodes"][0]["contextManagement"]["level"] == 1
    assert any(row["kind"] == "context_compacted" for row in result["events"])


@pytest.mark.parametrize("quota", [1, 2, 3])
def test_batch_requests_share_call_budget_and_audits(flows, monkeypatch, quota):
    _, version = flows["create"](one=True)
    rows = [evidence(f"direct-{index}", {"value": "x" * 900}) for index in range(12)]
    for row in rows:
        row["title"] = "直接资料" + row["id"]
    spec = deepcopy(version.definition)
    spec["nodes"][0]["instruction"] += " ".join(row["id"] for row in rows)
    with project_scope(flows["scope"]):
        _, version = catalog.register_flow(
            flows["admin"],
            {
                "code": "batch-" + uuid4().hex[:8],
                "name": "分批",
                "description": "归纳计费",
                "definition": spec,
            },
        )
    calls = install_model(monkeypatch, window=8192 + 256 + 2100)
    monkeypatch.setattr(engine, "input_evidence", lambda *args: deepcopy(rows))
    workflow, _ = start(flows, version)
    with project_scope(flows["scope"]):
        workflow.max_iterations = quota
        workflow.save(update_fields=["max_iterations"])
    result = advance(flows, workflow)
    assert result["status"] == ("queued" if quota == 3 else "waiting_approval"), (
        workflow.detail
    )
    assert len(calls) == quota
    saved = state(workflow)
    audits = saved["nodes"]["summarize"]["attempts"]
    requested = [row for row in audits if row["requested"]]
    assert len(saved["requestedIds"]) == len(requested) == quota
    assert sum(row.get("purpose") == "context_summary" for row in requested) == min(
        quota, 2
    )
    assert all(row["contextManagement"]["evidenceIds"] for row in requested)
    assert all(
        row["usage"]["total_tokens"] > 0 and row["contextManagement"]["level"] == 3
        for row in requested
    )


def test_context_wait_can_skip_retry_without_approving_or_restarting_previous_nodes(
    flows, monkeypatch
):
    _, version = flows["create"](one=True, human=True)
    rows = [evidence("oversized", {"text": "x" * 3000}), evidence("small")]
    calls = install_model(
        monkeypatch,
        tokenizer=lambda model, messages, *args: (
            1000000
            if '"id":"oversized"' in messages[1]["content"]
            else length_tokens(model, messages)
        ),
    )
    monkeypatch.setattr(engine, "input_evidence", lambda *args: deepcopy(rows))
    workflow, _ = start(flows, version)
    result = advance(flows, workflow)
    assert (
        workflow.status == "waiting_approval"
        and result["nodes"][0]["status"] == "waiting_context"
    )
    assert result["nodes"][0]["human"]["status"] == "pending" and not calls
    with project_scope(flows["scope"]):
        value = {
            "nodeId": "summarize",
            "revision": result["revision"],
            "decision": "retry_context",
            "feedback": "去除非必需补充",
            "skipEvidenceIds": ["oversized"],
            "idempotencyKey": uuid4().hex,
        }
        workflow = runtime.decide_flow(flows["user"], workflow, value)
        repeated = runtime.decide_flow(flows["user"], workflow, value)
        assert repeated.pk == workflow.pk
    result = advance(flows, workflow)
    assert len(calls) == 1 and workflow.status == "waiting_approval"
    assert (
        result["nodes"][0]["status"] == "waiting_human"
        and result["nodes"][0]["attempt"] == 1
    )
    assert result["nodes"][0]["human"]["status"] == "pending"
    assert [row["id"] for row in calls[0]["packet"]["evidence"]] == ["small"]
    assert calls[0]["packet"]["contextNotice"][0]["action"] == "user_skip"


def test_context_wait_stops_via_existing_control_channel(flows, monkeypatch):
    _, version = flows["create"](one=True)
    install_model(monkeypatch, tokenizer=lambda *args: 1000000)
    workflow, _ = start(flows, version)
    result = advance(flows, workflow)
    assert result["status"] == "waiting_approval"
    with project_scope(flows["scope"]):
        stopped = runtime.control_flow(flows["user"], workflow, "cancel")
        public = runtime.serialize_run(flows["user"], stopped, control_only=True)
    assert stopped.status == "cancelled" and public["events"] == []
    assert "contextRecovery" not in json.dumps(public) and "ledger" not in json.dumps(
        public
    )


def test_ledger_is_bounded_recent_records_retained_and_no_raw_samples(flows):
    _, version = flows["create"](one=True)
    workflow, _ = start(flows, version)
    with project_scope(flows["scope"]):
        values = state(workflow)
        base = deepcopy(values["nodes"]["summarize"])
        for index in range(32):
            identity = "completed-" + str(index)
            values["nodes"][identity] = deepcopy(base)
            item = values["nodes"][identity]
            item["executor"].update(
                summary="结" * 4000,
                findings=["要" * 2000] * 3,
                limitations=["限" * 2000] * 3,
            )
            item["outputs"] = {
                "evidence": [
                    {"id": f"result-{index}-{number}", "title": "标题" * 200}
                    for number in range(20)
                ]
            }
            complete_node(workflow, {"id": identity, "title": identity})
        ledger = values["ledger"]
        assert size(ledger) <= MAX_LEDGER_BYTES
        assert len(ledger["entries"]) == 32 and ledger["entries"][0]["compressed"]
        assert len(ledger["entries"][-1]["summary"].encode()) == 900
        assert ledger["entries"][-1]["evidenceCount"] == 20
        assert "sample" not in json.dumps(ledger)
        with pytest.raises(PermissionDenied):
            runtime.serialize_run(flows["admin"], workflow)


def test_projection_deduplicates_and_does_not_use_geology_fields():
    row = evidence(result={"sample": [1, 1, 2, 2, 3], "custom": {"text": "x" * 4000}})
    first = project_evidence([row])
    assert first == project_evidence([row])
    assert first[0][0]["result"]["sample"] == [1, 2, 3]
    assert first[1][0]["changes"][0]["originalCount"] == 5
    assert first[1][0]["changes"][0]["retainedCount"] == 3


def test_evidence_count_protection_waits_instead_of_disabling_the_limit(monkeypatch):
    rows = [evidence(f"source-{index}", {"value": "x" * 900}) for index in range(101)]
    with pytest.raises(ContextReviewRequired) as caught:
        prepare(monkeypatch, rows, 11000)
    assert caught.value.details["level"] == 3
    assert len(caught.value.details["evidence"]) == 101


def test_review_smaller_window_reexecutes_with_matching_evidence(flows, monkeypatch):
    _, version = flows["create"](one=True, ai=True)
    calls = install_model(monkeypatch)
    windows = iter([32768, 8000, 32768, 8000])
    monkeypatch.setattr(provider, "model_window", lambda model: next(windows))
    monkeypatch.setattr(
        engine, "input_evidence", lambda *args: [evidence(result={"text": "x" * 18000})]
    )
    workflow, _ = start(flows, version)
    first = advance(flows, workflow)
    assert first["status"] == "queued" and len(calls) == 1
    assert first["nodes"][0]["attempt"] == 1
    second = advance(flows, workflow)
    assert second["status"] == "queued", workflow.detail
    assert len(calls) == 3 and second["nodes"][0]["attempt"] == 1
    assert calls[-1]["packet"]["evidence"][:-1] == calls[-2]["packet"]["evidence"]
    assert calls[-1]["packet"]["contextNotice"] == calls[-2]["packet"]["contextNotice"]
    assert any(event["kind"] == "review_context_repack" for event in second["events"])


def test_required_source_cannot_be_skipped_after_index_projection(flows, monkeypatch):
    from apps.agent.business_flow_execution import execute_node
    from apps.agent.business_flow_review import review_node
    from apps.agent.business_flow_model import actual_context

    _, version = flows["create"](one=True, ai=True)
    calls = install_model(monkeypatch)
    windows = iter([8192 + 256 + 3500, 6000])
    monkeypatch.setattr(provider, "model_window", lambda model: next(windows))
    rows = [evidence(f"source-{index}", {"value": "x" * 900}) for index in range(30)]
    rows[0]["required"] = True
    workflow, _ = start(flows, version)
    node = version.definition["nodes"][0]
    with project_scope(flows["scope"]):
        result = execute_node(
            workflow, node, 1, rows, guard=engine.live_guard(workflow)
        )
        assert result["audit"]["contextManagement"]["level"] == 2
        snapshot = actual_context(workflow, node["id"])
        assert snapshot["requiredEvidenceIds"] == ["source-0"]
        with pytest.raises(ContextReviewRequired) as caught:
            review_node(
                workflow,
                node,
                1,
                snapshot["evidence"],
                guard=engine.live_guard(workflow),
            )
    assert len(calls) == 1
    assert next(
        row for row in caught.value.details["evidence"] if row["id"] == "source-0"
    )["required"]


def test_context_recovery_rejects_required_skip_stale_decision_and_approval(
    flows, monkeypatch
):
    _, version = flows["create"](one=True)
    install_model(monkeypatch, tokenizer=lambda *args: 1000000)
    workflow, _ = start(flows, version)
    result = advance(flows, workflow)
    required = result["nodes"][0]["contextRecovery"]["evidence"][0]
    assert required["required"]
    value = {
        "nodeId": "summarize",
        "revision": result["revision"],
        "decision": "retry_context",
        "feedback": "",
        "idempotencyKey": uuid4().hex,
    }
    with project_scope(flows["scope"]):
        with pytest.raises(ComputeError, match="不能跳过"):
            runtime.decide_flow(
                flows["user"], workflow, {**value, "skipEvidenceIds": [required["id"]]}
            )
        with pytest.raises(ComputeError, match="版本已变化"):
            runtime.decide_flow(
                flows["user"], workflow, {**value, "revision": result["revision"] - 1}
            )
        with pytest.raises(ComputeError, match="不能批准"):
            runtime.decide_flow(
                flows["user"], workflow, {**value, "decision": "approve"}
            )


def test_user_scope_is_applied_to_projection_with_accurate_notice(monkeypatch):
    row = evidence(result={"sample": list(range(1240)), "text": "字" * 4000})
    actual, notices = project_evidence([row], {"maxItems": 1, "maxTextCharacters": 250})
    assert actual[0]["result"]["sample"] == [0]
    assert len(actual[0]["result"]["text"]) == 250
    assert notices[0]["changes"] == [
        {
            "path": "result.sample",
            "unit": "items",
            "originalCount": 1240,
            "retainedCount": 1,
        },
        {
            "path": "result.text",
            "unit": "characters",
            "originalCount": 4000,
            "retainedCount": 250,
        },
    ]
    original = packet([row])
    original["contextScope"] = {"maxItems": 1, "maxTextCharacters": 250}
    monkeypatch.setattr(provider, "count_tokens", length_tokens)
    scoped, _, audit = prepare_packet(
        original,
        "执行",
        None,
        {
            "maxContextTokens": 10000,
            "maxOutputTokens": 512,
            "maxContextBytes": 192 * 1024,
        },
        32768,
        direct_ids=set(),
        summarize=lambda *args: pytest.fail("不应归纳"),
        checked=lambda: None,
    )
    assert audit["level"] == 1
    assert scoped["evidence"][0]["result"]["sample"] == [0]


def test_withdrawn_source_cannot_leak_ledger_or_snapshot_on_cancel(flows, monkeypatch):
    from apps.catalog.models import DataResource

    _, version = flows["create"]()
    install_model(monkeypatch)
    workflow, _ = start(flows, version)
    advance(flows, workflow)
    assert state(workflow)["ledger"]["entries"]
    with project_scope(flows["scope"]):
        DataResource.objects.filter(pk=flows["resource"].pk).update(
            owner_only=True, maintainer=flows["other"]
        )
        with pytest.raises(PermissionDenied):
            runtime.serialize_run(flows["user"], workflow)
        stopped = runtime.control_flow(flows["user"], workflow, "cancel")
        public = runtime.serialize_run(flows["user"], stopped, control_only=True)
    assert public["events"] == []
    assert all(
        node["executor"] == {"status": "unavailable"} for node in public["nodes"]
    )
    assert all(
        key not in json.dumps(public)
        for key in (
            "ledger",
            "contextSnapshots",
            "executionContextId",
            "contextRecovery",
        )
    )
