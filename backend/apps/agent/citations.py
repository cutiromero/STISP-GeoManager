"""Keep evidence references local to the run that actually read their sources."""

import json
import re
from uuid import UUID

from django.core.exceptions import ValidationError


CURRENT_REFERENCE = re.compile(r"\[\s*证据\s*([^\]\n]*)\]")
HISTORICAL_REFERENCE = re.compile(r"\[\s*历史(?:运行|任务)[^\]\n]*证据[^\]\n]*\]")


def historical_text(text: str, run_id: int) -> str:
    return CURRENT_REFERENCE.sub(
        lambda match: f"[历史运行 {run_id} 的证据 {match[1].strip()}]", text
    )


def source_locators(item: dict) -> list[dict]:
    """Extract only known tool identifiers, never old conclusions or citations."""
    result, tool = item.get("result", {}), item.get("tool")
    if not isinstance(result, dict):
        return []
    locations = []

    def add(values):
        locator = {}
        for key, value in values.items():
            if key == "taskId":
                try:
                    locator[key] = str(UUID(str(value)))
                except (ValueError, TypeError, AttributeError):
                    continue
            elif type(value) is int and value > 0:
                locator[key] = value
        if locator and locator not in locations:
            locations.append(locator)

    def task(row):
        add({"taskId": row.get("taskId"), "versionId": row.get("versionId")})
        outputs = row.get("outputs", [])
        if isinstance(row.get("output"), dict):
            outputs = [row["output"]]
        for output in outputs:
            if isinstance(output, dict):
                add(
                    {
                        "taskId": row.get("taskId"),
                        "outputId": output.get("id"),
                        "resourceId": output.get("resourceId"),
                    }
                )

    if tool in {
        "execute_operator",
        "get_compute_task",
        "import_compute_result",
        "read_compute_output",
    }:
        task(result)
    elif tool == "list_compute_tasks":
        for row in result.get("items", []):
            if isinstance(row, dict):
                task(row)
    elif tool in {"search_knowledge", "read_knowledge_document"}:
        for row in result.get("items", []):
            if isinstance(row, dict):
                add({"entryId": row.get("id")})
        for row in result.get("documents", []):
            if isinstance(row, dict):
                add({"documentId": row.get("documentId")})
    elif tool == "check_knowledge_constraints":
        for row in result.get("findings", []):
            if isinstance(row, dict):
                add({"entryId": row.get("entryId")})
    elif tool == "list_compute_algorithms":
        for algorithm in result.get("items", []):
            if isinstance(algorithm, dict):
                for version in algorithm.get("versions", []):
                    if isinstance(version, dict):
                        add({"versionId": version.get("id")})
    return locations


def historical_answer(run) -> str:
    """Keep conversation background without importing old tool citations/results."""
    answer = historical_text(run.answer, run.id)
    if not run.evidence:
        return answer
    sources = [
        {
            "historyRunId": run.id,
            "historyReference": f"历史运行 {run.id} 的证据 {item.get('id')}",
            "tool": item.get("tool"),
            "name": historical_text(item.get("name") or "", run.id),
            "resourceId": item.get("resourceId"),
            "sourceLocators": source_locators(item),
        }
        for item in run.evidence
    ]
    return (
        answer
        + "\n历史来源索引（仅作背景，不是本轮证据；需要引用时重新实际查询或检索）："
        + json.dumps(sources, ensure_ascii=False)
    )


def validate_answer_citations(answer: str, evidence: list, *, is_agent: bool) -> None:
    """Reject unsupported citations through the existing model-correction loop."""
    allowed = (
        {item["id"] for item in evidence if type(item.get("id")) is int}
        if is_agent
        else set()
    )
    invalid = []
    for match in CURRENT_REFERENCE.finditer(answer):
        reference = match[1].strip()
        if not re.fullmatch(r"[1-9][0-9]*(?:\s*[,，、;；]\s*[1-9][0-9]*)*", reference):
            invalid.append(match[0])
            continue
        numbers = {int(value) for value in re.split(r"\s*[,，、;；]\s*", reference)}
        if not numbers <= allowed:
            invalid.append(match[0])
    invalid.extend(match[0] for match in HISTORICAL_REFERENCE.finditer(answer))
    if invalid:
        detail = "、".join(dict.fromkeys(invalid))[:120]
        action = (
            "请重新实际查询或检索有关来源后，使用本轮工具返回的evidenceIds或citation；"
            if is_agent
            else "快速对话没有平台证据权限；请依据用户提供的内容说明，不能声称核实平台资料；"
        )
        raise ValidationError(
            f"回答引用不属于本轮真实证据：{detail}。历史编号不能映射为本轮编号。"
            + action
            + "无法核实的具体结论应删除或明确为待核实，不能仅删除引用而保留其事实断言。"
        )
