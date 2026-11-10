"""只存摘要与引用的有界任务台账；不额外请求模型。"""

from copy import deepcopy
import json

from .state import state

MAX_LEDGER_BYTES = 48 * 1024
MAX_RECORD_BYTES = 4096
MAX_OLD_RECORD_BYTES = 1024
RECENT_RECORDS = 2
MAX_REFERENCES = 4


def size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def professional_ledger(workflow):
    entries = []
    for stage in workflow.plan.get("stages", []):
        if stage.get("status") != "completed":
            continue
        entries.append(
            {
                "nodeId": stage["name"],
                "summary": text(stage.get("decision", {}).get("resultSummary"), 240),
                "taskId": stage.get("taskId"),
                "outputs": [
                    {key: row.get(key) for key in ("outputId", "checksum", "key")}
                    for row in stage.get("results", [])
                ],
                "humanApproved": bool(
                    stage.get("manualApproved") or stage.get("modificationsApproval")
                ),
            }
        )
    ledger = {
        "goal": text(workflow.goal, 1024),
        "entries": entries,
        "scope": "台账仅为索引；科学事实与批准范围以本次实际证据为准",
    }
    state(workflow)["ledger"] = deepcopy(ledger)
    return ledger


def text(value, maximum):
    return str(value or "").encode()[:maximum].decode("utf-8", errors="ignore")


def _bound(record, maximum):
    original = size(record)
    while size(record) > maximum:
        arrays = [
            key
            for key in ("sources", "evidence", "findings", "limitations")
            if record.get(key)
        ]
        if arrays:
            longest = max(arrays, key=lambda key: size(record[key]))
            record[longest].pop()
        else:
            for key in ("summary", "title"):
                record[key] = text(
                    record.get(key), max(24, len(record.get(key, "").encode()) // 2)
                )
    if original > size(record):
        record["compressed"] = True
    return record


def complete_node(workflow, node):
    values = state(workflow)
    ledger = values.setdefault(
        "ledger", {"goal": text(workflow.goal, 1024), "entries": [], "unresolved": []}
    )
    item = values["nodes"][node["id"]]
    actor = item["executor"]
    snapshot = values.get("contextSnapshots", {}).get(
        item.get("executionContextId"), {}
    )
    sources = snapshot.get("evidence", [])
    outputs = item.get("outputs", {}).get("evidence", [])
    record = {
        "nodeId": node["id"],
        "title": text(node["title"], 240),
        "summary": text(actor.get("summary"), 900),
        "findings": [text(value, 240) for value in actor.get("findings", [])[:3]],
        "limitations": [text(value, 180) for value in actor.get("limitations", [])[:3]],
        "limitationCount": len(actor.get("limitations", [])),
        "evidenceCount": len(outputs),
        "sourceCount": len(sources),
        "evidence": [
            {"id": row["id"], "title": text(row["title"], 120)}
            for row in outputs[:MAX_REFERENCES]
        ],
        "sources": [
            {
                "id": row["id"],
                "title": text(row["title"], 120),
                "summary": text(
                    row.get("summary")
                    or row.get("result", {}).get(
                        "summary", "资料已在该节点读取；这里只保留引用。"
                    )
                    if isinstance(row.get("result", {}), dict)
                    else "资料已在该节点读取；这里只保留引用。",
                    180,
                ),
            }
            for row in sources[:MAX_REFERENCES]
        ],
        "reviewDecision": item.get("reviewer", {}).get("decision", "not_required"),
        "humanDecision": item["human"]["status"],
    }
    _bound(record, MAX_RECORD_BYTES - 32)
    entries = [row for row in ledger["entries"] if row["nodeId"] != node["id"]]
    entries.append(record)
    for index in range(max(0, len(entries) - RECENT_RECORDS)):
        if (
            not entries[index].get("compressed")
            or size(entries[index]) > MAX_OLD_RECORD_BYTES
        ):
            older = deepcopy(entries[index])
            older.update(
                summary=text(older["summary"], 96),
                title=text(older["title"], 96),
                findings=[],
                compressed=True,
            )
            older["limitations"] = [
                text(value, 96) for value in older.get("limitations", [])[:1]
            ]
            for key in ("sources", "evidence"):
                for reference in older[key]:
                    reference["title"] = text(reference["title"], 48)
                    if "summary" in reference:
                        reference["summary"] = text(reference["summary"], 60)
            _bound(older, MAX_OLD_RECORD_BYTES - 32)
            entries[index] = older
    ledger["entries"] = entries
    ledger["unresolved"] = [
        {"nodeId": row["nodeId"], "limitations": row["limitations"][:1]}
        for row in entries
        if row.get("limitations")
    ][-8:]
    ledger["unresolvedMeaning"] = "已完成节点报告的限制；未自动判定其后续已解决。"
    if size(ledger) > MAX_LEDGER_BYTES:
        raise ValueError("任务台账超过内部存储保护上限")
    return ledger


def current_ledger(workflow):
    return deepcopy(
        state(workflow).get(
            "ledger",
            {"goal": text(workflow.goal, 1024), "entries": [], "unresolved": []},
        )
    )
