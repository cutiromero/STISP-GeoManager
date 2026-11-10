"""七节点预算审计：真实上传规模、保守分词、协议桩与完整事实。"""

from copy import deepcopy
import json
import math
from pathlib import Path
import re

import geopandas as gpd
import pytest
import rasterio

from apps.agent import context, provider
from apps.agent.business_flow_context import (
    ContextReviewRequired,
    prepare_auxiliary_request,
)
from apps.agent.demo_decisions import decide
from apps.agent.demo_workflow import _pause
from apps.agent.geology_multi_review import proposal, selected_edits
from apps.agent.generic_mapping import _payload, _validate
from apps.agent.policy import default_policy
from apps.business_flows import legacy
from apps.business_flows.state import digest, state
from apps.projects.context import project_scope
from tests.integration import test_agent, test_business_flow_legacy
from tests.integration.test_decision_input_budget import expand
from tests.integration.test_demo_decision_batches import scenario

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT.parent / "逻辑推理测试数据_按草案" / "上传用"
OUTPUT = ROOT / ".runtime" / "task-h" / "budget-audit"
SCALES = (1, 5, 20)
WINDOWS = (32768, 16384)
HAN_TOKENS = 1
OTHER_CHARACTERS_PER_TOKEN = 3
MESSAGE_OVERHEAD_TOKENS = 16
OUTPUT_TOKENS = 4096
MODEL_CALL_LIMIT = 256
legacy_flow = test_business_flow_legacy.legacy_flow
setup_agent = test_agent.setup_agent

pytestmark = [pytest.mark.django_db, pytest.mark.efficiency]


def conservative_tokens(model, messages, *args):
    text = "".join(row["content"] for row in messages)
    han = len(re.findall(r"[\u3400-\u9fff\U00020000-\U0003134f]", text))
    return (
        han * HAN_TOKENS
        + math.ceil((len(text) - han) / OTHER_CHARACTERS_PER_TOKEN)
        + MESSAGE_OVERHEAD_TOKENS * len(messages)
    )


@pytest.fixture(scope="module")
def upload_scale():
    if not SOURCE.is_dir():
        pytest.fail(f"预算审计缺少上传用测试资料：{SOURCE}")
    frames = {
        "lithology": gpd.read_file(
            SOURCE / "海德乌拉_模拟识别岩性图.gpkg", ignore_geometry=True
        ),
        "faults": gpd.read_file(
            SOURCE / "示范区构造_模拟识别.gpkg", ignore_geometry=True
        ),
    }
    rasters = []
    for path in sorted(SOURCE.glob("*.tif")):
        with rasterio.open(path) as source:
            rasters.append(
                {
                    "name": path.name,
                    "bands": source.count,
                    "width": source.width,
                    "height": source.height,
                }
            )
    units = sorted({str(value) for value in frames["lithology"]["code"].dropna()})
    return frames, rasters, units


def audit_sources(env, scale, source):
    frames, rasters, units = source
    count = (sum(len(frame) for frame in frames.values()) + len(rasters)) * scale
    template, _, results = scenario(count)
    group_count = (len(units) + 1 + len(rasters)) * scale
    entries = []
    for index in range(group_count // scale):
        entry = deepcopy(template.evidence[0])
        entry.update(id=200 + index, title=f"审计合成分组{index}")
        entry["trialBinding"]["ruleId"] = f"L-AUDIT-{index:04d}"
        entries.append(entry)
    for index, row in enumerate(results[0]["rows"]):
        entry = entries[index % len(entries)]
        row["rule_id"] = entry["trialBinding"]["ruleId"]
        row["snapshot_hash"] = digest({"replica": index // (count // scale)})
        row["measurements_json"] = json.dumps(
            {"area_m2": index + 1, "source_object_index": index % (count // scale)}
        )
    for item in results:
        item.update(
            kind="table",
            scope="all",
            rowCount=len(item["rows"]),
            metadata={
                "qualityCheck": {
                    "status": "passed",
                    "issues": [],
                    "metrics": {"objectCount": count},
                }
            },
        )
    workflow = env["create"]()
    workflow.max_iterations = MODEL_CALL_LIMIT
    workflow.evidence = entries
    workflow.plan = {
        **template.plan,
        "phase": "decide",
        "stageIndex": 0,
        "inputSnapshots": {},
        "inputs": {},
        "trialRulesSnapshot": {},
        "trialRuleBindings": [
            {"id": row["id"], "revision": row["revision"], **row["trialBinding"]}
            for row in entries
        ],
        "stages": [
            {
                "name": name,
                "identifier": identifier,
                "parameters": {},
                "status": "pending",
            }
            for name, identifier in [
                ("check", "geology-multi-check"),
                ("apply", "geology-multi-apply"),
                ("recheck", "geology-multi-check"),
                ("relations", "geology-multi-relations"),
                ("prospect", "geology-multi-prospect"),
                ("final_analysis", "finish"),
            ]
        ],
    }
    workflow.plan_hash = digest(workflow.plan)
    workflow.save()
    return (
        workflow,
        results,
        {
            "objects": count,
            "groups": group_count,
            "issues": count,
            "rasterProfiles": rasters,
        },
    )


@pytest.mark.parametrize("window", WINDOWS)
@pytest.mark.parametrize("scale", SCALES)
def test_seven_node_model_budget_audit(
    request, upload_scale, monkeypatch, settings, scale, window
):
    env = request.getfixturevalue("legacy_flow")
    settings.AGENT_MODELS[0] = {
        **settings.AGENT_MODELS[0],
        "model_id": "task-h-protocol-stub",
    }
    policy = {**default_policy(), "maxOutputTokens": OUTPUT_TOKENS}
    monkeypatch.setattr(provider, "model_window", lambda model: window)
    monkeypatch.setattr(provider, "count_tokens", conservative_tokens)
    monkeypatch.setattr(context, "count_tokens", conservative_tokens)
    monkeypatch.setattr("apps.agent.demo_decisions.resource_context", lambda *args: [])
    requests, waits, transitions = [], [], []
    active = {"point": "inputs", "attempt": None}
    rejected = set()

    def stream(model, messages, maximum, guard, **options):
        guard()
        tokens = conservative_tokens(model, messages)
        budget = min(policy["maxContextTokens"], window - maximum - 256)
        payload = json.loads(messages[1]["content"])
        payload = expand(payload, payload.get("contextDefinitions", {}))
        if "node" in payload:
            budget = min(budget, 49152)
        if payload.get("modelBatch"):
            budget = min(budget, 15000)
        assert tokens <= budget
        attempt = active.get("attempt") or {}
        if "node" in payload:
            attempt = state(workflow)["nodes"][payload["node"]["id"]]["reviewer"].get(
                "audit", {}
            )
        point = (
            payload["node"]["id"] + "-review" if "node" in payload else active["point"]
        )
        requests.append(
            {
                "point": point,
                "tokens": tokens,
                "budget": budget,
                "level": attempt.get("contextManagement", {}).get("level", 0),
                "projectionRecipe": attempt.get("contextManagement", {}).get(
                    "projectionRecipe", attempt.get("budgetLevel", 0)
                ),
            }
        )
        if active["point"] == "inputs":
            value = {
                "roles": {
                    role: {
                        "name": {
                            "field": fields["fields"][0]["name"],
                            "reason": "按实际字段与示例提出建议，仍需人工确认",
                        }
                    }
                    for role, fields in payload["roles"].items()
                }
            }
        elif "node" in payload:
            change = point == "finish-review" and point not in rejected
            rejected.add(point)
            value = {
                "decision": "request_changes" if change else "accept",
                "reason": "明确未展示对象不在本次审核范围"
                if change
                else "所示统计与批准范围一致",
                "issues": [
                    {
                        "code": "scope",
                        "message": "补充证据范围说明",
                        "evidenceIds": ["node-result"],
                    }
                ]
                if change
                else [],
                "repairInstructions": "只核对本次完整统计与已展示内容，不扩大批准范围"
                if change
                else "",
                "evidenceIds": [row["id"] for row in payload["evidence"]],
            }
        else:
            if active["point"] == "check" and "check" not in rejected:
                rejected.add("check")
                yield "not-json"
                return
            refs = payload["availableEvidence"]
            groups = [
                group
                for item in payload["actualResults"]
                if item.get("key") == "issues"
                for group in item.get("groups", [])
            ]
            rules = {group["rule_id"] for group in groups}
            identities = {
                str(row["id"])
                for row in payload["knowledge"]
                if row.get("trialBinding", {}).get("ruleId") in rules
            }
            chosen = [row for row in refs if row["kind"] == "output"][-3:]
            chosen += [
                row
                for row in refs
                if row["kind"] == "knowledge" and str(row["id"]) in identities
            ]
            if not any(row["kind"] == "knowledge" for row in chosen):
                chosen += [row for row in refs if row["kind"] == "knowledge"][:1]
            value = {
                "decision": {
                    "problem": "预算回归合成问题，不作地质结论",
                    "findings": ["统计使用完整源数据；逐对象审核仅限本批成员"],
                    "judgement": "本次仅提出建议，后续按用户实际批准范围执行",
                    "uncertainties": ["未展示明细不作判断"],
                    "nextAction": payload["allowedAction"],
                    "algorithmReason": "遵循固定科学图与人工边界",
                    "evidenceRefs": chosen,
                    "resultSummary": "按完整统计核对本节点",
                },
                "edits": [
                    {
                        "group_id": group["group_id"],
                        "disposition": "suggested",
                        "excluded_issue_ids": [],
                        "reason": "仅提出本批成员的建议，仍须用户批准",
                    }
                    for group in groups
                ]
                if payload["allowedAction"] == "geology-multi-apply"
                else [],
            }
        yield json.dumps(value, ensure_ascii=False)

    monkeypatch.setattr(provider, "stream", stream)
    with project_scope(env["scope"]):
        workflow, original_results, sizes = audit_sources(env, scale, upload_scale)
        model = __import__("apps.agent.config", fromlist=["registry"]).registry()[
            workflow.model
        ]
        frames, _, _ = upload_scale
        roles = [
            {
                "role": role,
                "label": role,
                "_profile": {
                    "fields": [
                        {
                            "name": str(name),
                            "type": str(frame[name].dtype),
                            "samples": [
                                str(value) for value in frame[name].dropna().head(8)
                            ],
                        }
                        for name in frame.columns
                    ]
                },
                "targets": [{"key": "name", "label": "原始字段", "required": True}],
                "fields": list(frame.columns),
            }
            for role, frame in frames.items()
        ]
        messages, management = prepare_auxiliary_request(
            [
                {"role": "system", "content": "仅提出字段对应建议，必须等待用户确认"},
                {
                    "role": "user",
                    "content": json.dumps(_payload(roles), ensure_ascii=False),
                },
            ],
            model,
            policy,
            window,
            node_id="inputs",
            checked=lambda: None,
        )
        _validate("".join(stream(model, messages, OUTPUT_TOKENS, lambda: None)), roles)
        transitions.append(
            {"node": "inputs", "states": ["executing", "waiting_human", "succeeded"]}
        )
        workflow.plan["confirmedMapping"] = {
            role["role"]: {"name": role["fields"][0]} for role in roles
        }
        collected = []
        for index, stage in enumerate(workflow.plan["stages"]):
            workflow.plan["stageIndex"] = index
            workflow.current_step = stage["name"]
            active["point"] = stage["name"]

            def record(attempt):
                active["attempt"] = attempt
                if attempt["status"] == "requesting":
                    if workflow.plan["actualModelCallCount"] >= MODEL_CALL_LIMIT:
                        from apps.agent.decision_budget import BudgetReviewRequired

                        raise BudgetReviewRequired(
                            "模型请求额度不足，保留当前节点等待处理"
                        )
                    workflow.plan["actualModelCallCount"] += 1
                    attempt["requested"] = True

            def produce():
                active["point"] = stage["name"]
                return decide(
                    workflow,
                    env["user"],
                    policy,
                    stage,
                    collected,
                    lambda: None,
                    record,
                )

            try:
                workflow.iteration += 1
                initial = produce()
                workflow.save()
                active["point"] = (
                    "finish" if stage["identifier"] == "finish" else stage["name"]
                ) + "-review"
                result = legacy.review_decision(
                    workflow,
                    env["user"],
                    policy,
                    stage,
                    collected,
                    initial,
                    lambda: None,
                    produce,
                )
                stage.update(decision=result[0], edits=result[1])
            except ContextReviewRequired as error:
                stage["contextBudgetReview"] = {**error.details, "reason": str(error)}
                _pause(workflow, stage, str(error))
                waits.append(
                    {
                        "point": active["point"],
                        "details": error.details,
                        "reason": str(error),
                    }
                )
                assert workflow.status == "waiting_approval"
                break
            if stage["name"] == "apply":
                review, edits = proposal(workflow, stage, collected)
                workflow.plan["modificationReview"] = review
                selected = [
                    row["id"]
                    for row in review["suggestions"]
                    if row["status"] == "suggested"
                ]
                stage["approvedEdits"] = selected_edits(edits, review, selected)
                stage["modificationsApproval"] = {
                    "selectedSuggestionIds": selected,
                    "proposalHash": review["proposalHash"],
                }
                review["approvedSuggestionIds"] = selected
            stage.update(status="completed", taskId=f"audit-{stage['name']}")
            outputs = deepcopy(original_results)
            if stage["name"] in {"check", "recheck"}:
                if stage["name"] == "recheck":
                    outputs[0]["rows"] = outputs[0]["rows"][::5]
                    outputs[0]["rowCount"] = len(outputs[0]["rows"])
            elif stage["name"] == "apply":
                outputs = [
                    {
                        **outputs[1],
                        "key": "changes",
                        "rows": [
                            {
                                "element": "lithology",
                                "rule_id": row["rule_id"],
                                "action": "set_code",
                                "actual_changed": "1",
                            }
                            for row in original_results[0]["rows"]
                        ],
                        "rowCount": sizes["issues"],
                    }
                ]
            else:
                outputs = [outputs[1]]
            for offset, output in enumerate(outputs):
                output.update(
                    taskId=stage["taskId"],
                    outputId=1000 + index * 10 + offset,
                    checksum=digest(output),
                )
            stage["results"] = outputs
            collected.extend(outputs)
            transitions.append(
                {
                    "node": "finish"
                    if stage["identifier"] == "finish"
                    else stage["name"],
                    "states": ["executing", "succeeded"],
                }
            )
        if not waits:
            workflow.status = "succeeded"
            assert len(transitions) == 7
        assert workflow.status != "failed"
        result = {
            "scale": scale,
            "window": window,
            "sizes": sizes,
            "requests": requests,
            "waits": waits,
            "transitions": transitions,
            "status": workflow.status,
        }
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / f"{scale}x-{window}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
        print("\n规模 | 窗口 | 调用点 | 请求数 | 最大token | 预算 | 档位 | 等待")
        for point in dict.fromkeys(row["point"] for row in requests):
            rows = [row for row in requests if row["point"] == point]
            print(
                f"{scale}x | {window} | {point} | {len(rows)} | {max(row['tokens'] for row in rows)} | {min(row['budget'] for row in rows)} | {max(row['level'] for row in rows)} | 否"
            )
        for wait in waits:
            print(
                f"{scale}x | {window} | {wait['point']} | 0 | — | — | — | {wait['reason']}"
            )
