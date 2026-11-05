"""Deterministic request projections; the complete source stays in stage audit."""

import copy
import json
import re
from collections import Counter


MAX_LEVEL = 4
REFERENCE_NOTE = (
    "contextDefinitions中的编号由{$ref:编号}引用，须按原值展开理解。"
    "知识正文可能为节选，编号、修订、适用条件、例外和结构化规则保留；"
    "不能从未展示的正文推断依据，证据不足须request_review。"
    "分组count及measurementRanges为完整快照统计，不是代表样本的统计。"
)


class BudgetReviewRequired(Exception):
    pass


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _expand_knowledge(payload):
    def expand(value):
        if isinstance(value, dict):
            if set(value) == {"sameAs"} and isinstance(value["sameAs"], str):
                target = payload
                for name, index in re.findall(r"([\w]+)|\[(\d+)\]", value["sameAs"]):
                    target = target[name] if name else target[int(index)]
                return expand(target)
            return {key: expand(item) for key, item in value.items()}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value

    expanded = copy.deepcopy(payload)
    expanded["knowledge"] = expand(payload.get("knowledge", []))
    return expanded


def _deduplicate(payload):
    counts = Counter()

    def count(value):
        if isinstance(value, (dict, list, str)):
            signature = dumps(value)
            if len(signature) >= 160:
                counts[signature] += 1
        if isinstance(value, dict):
            for item in value.values():
                count(item)
        elif isinstance(value, list):
            for item in value:
                count(item)

    count(payload)
    definitions, identities = {}, {}

    def project(value, *, definition=False):
        if not definition and isinstance(value, (dict, list, str)):
            signature = dumps(value)
            if counts[signature] > 1:
                if signature not in identities:
                    identity = f"r{len(identities) + 1}"
                    identities[signature] = identity
                    definitions[identity] = project(value, definition=True)
                return {"$ref": identities[signature]}
        if isinstance(value, dict):
            return {key: project(item) for key, item in value.items()}
        if isinstance(value, list):
            return [project(item) for item in value]
        return value

    projected = project(payload, definition=True)
    projected["contextDefinitions"] = definitions
    projected["contextProjectionNote"] = REFERENCE_NOTE
    return projected


def _summary(value, limit):
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…（节选）"
    if isinstance(value, list):
        return [_summary(item, limit) for item in value]
    if isinstance(value, dict):
        return {key: _summary(item, limit) for key, item in value.items()}
    return value


def _history(value):
    if not isinstance(value, dict):
        return value
    return {
        key: _summary(item, 320)
        for key, item in value.items()
        if key
        in {
            "workflowId",
            "oldDecision",
            "judgement",
            "resultSummary",
            "nextAction",
            "evidenceRefs",
            "actualResultOutputIds",
            "oldContextChecksum",
            "newContextChecksum",
            "addedEvidence",
        }
    }


def project_payload(original, level):
    if not level:
        return copy.deepcopy(original)
    payload = _expand_knowledge(original)
    bindings = {}
    for role in payload.get("inputRoles", []):
        if role.get("role") == "rules":
            for row in role.get("rows", []):
                if row.get("knowledge_id"):
                    bindings[row.get("rule_id")] = {
                        "id": row["knowledge_id"],
                        "revision": row.get("knowledge_revision"),
                    }
    for entry in payload.get("knowledge", []):
        bound = entry.get("trialBinding", {})
        if bound.get("ruleId"):
            bindings[bound["ruleId"]] = {
                "id": entry["id"],
                "revision": entry["revision"],
            }
        for key in ("statement", "explanation", "content", "body", "description"):
            text = entry.get(key)
            if isinstance(text, str) and len(text) > 160:
                passages = re.findall(r"[^。；\n]+[。；\n]?", text)
                entry[key] = "".join(dict.fromkeys(passages))
    for result in payload.get("actualResults", []):
        for group in result.get("groups", []):
            if group.get("rule_id") in bindings:
                group["requiredKnowledgeRefs"] = [bindings[group["rule_id"]]]
    if level >= 2:
        rule_texts = {
            entry.get("trialBinding", {}).get("ruleId"): dumps(
                entry.get("ruleConfig", {})
            )
            for entry in payload.get("knowledge", [])
        }
        for result in payload.get("actualResults", []):
            for group in result.get("groups", []):
                rule_text = rule_texts.get(group.get("rule_id"), "")
                group["samples"] = group.get("samples", [])[:1] if level < 4 else []
                for sample in group["samples"]:
                    if "measurements_json" in sample:
                        measurements = json.loads(sample["measurements_json"] or "{}")
                        sample["measurements_json"] = dumps(
                            {
                                key: value
                                for key, value in measurements.items()
                                if key in rule_text
                            }
                        )
                    if "reason" in sample:
                        sample["reason"] = _summary(sample["reason"], 240)
    if level >= 3:
        relevant = {
            group.get("rule_id")
            for result in payload.get("actualResults", [])
            for group in result.get("groups", [])
        }
        for entry in payload.get("knowledge", []):
            active = (
                not relevant or entry.get("trialBinding", {}).get("ruleId") in relevant
            )
            for key in ("statement", "explanation", "content", "body", "description"):
                if key in entry:
                    entry[key] = _summary(
                        entry[key], (800 if level == 3 else 256) if active else 120
                    )
        payload["previousDecisions"] = [
            _history(item) for item in payload.get("previousDecisions", [])
        ]
        previous = payload.get("previousAnalysis")
        if isinstance(previous, dict):
            payload["previousAnalysis"] = _history(previous)
            if "oldDecision" in previous:
                payload["previousAnalysis"]["oldDecision"] = _history(
                    previous["oldDecision"]
                )
    return _deduplicate(payload)


def projected_messages(messages, payload, level):
    projected = [dict(item) for item in messages[:2]]
    if level:
        projected[0]["content"] += (
            "预算投影使用contextDefinitions及$ref引用，先解引用再判断；"
            "节选不构成额外知识依据，缺失依据须request_review。"
        )
        projected[1]["content"] = dumps(project_payload(payload, level))
    return projected


def budget_review(stage, payload, error):
    stage["modelRequestPayload"] = copy.deepcopy(payload)
    stage["contextBudgetReview"] = {"reason": str(error), "maxLevel": MAX_LEVEL}
    raise BudgetReviewRequired(
        "必要证据在分级压缩后仍超出模型输入预算，未提交本阶段计算。"
        "请调整模型窗口后继续分析，或缩小资料范围重新发起；完整证据和请求审计已保留。"
    )
