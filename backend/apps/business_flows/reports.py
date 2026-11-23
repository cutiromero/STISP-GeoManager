"""Render only completed, source-bound outcomes; no model or filesystem rescan."""

from .definitions import concise_definition
from .state import binding, state


def render_report(workflow):
    spec = binding(workflow)
    value = state(workflow)
    if concise_definition(spec["definitionSnapshot"]):
        return concise_report(workflow, spec, value)
    lines = [
        f"# {spec['name']}报告",
        "",
        f"分析目标：{workflow.goal}",
        "",
        f"业务流版本：{spec['versionId']}",
        "",
        "## 结论与适用范围",
        "",
        value.get("answer", workflow.detail),
        "",
        "## 节点结果与审核",
        "",
    ]
    for node in spec["definitionSnapshot"]["nodes"]:
        item = value["nodes"][node["id"]]
        lines.extend(
            [f"### {node['title']}", "", item["executor"].get("summary", ""), ""]
        )
        lines.extend(f"- {entry}" for entry in item["executor"].get("findings", []))
        lines.extend(
            f"- 适用限制：{entry}" for entry in item["executor"].get("limitations", [])
        )
        if node["review"]["ai"]:
            lines.extend(
                [
                    "",
                    "独立审核：" + item["reviewer"].get("reason", "未记录"),
                    f"本节点执行次数：{item['attempt']}",
                    "",
                ]
            )
        if item["human"]["required"]:
            lines.extend(
                [
                    "人工决定："
                    + (
                        "已由用户批准"
                        if item["human"]["status"] == "approved"
                        else "未批准"
                    ),
                    item["human"].get("reason", ""),
                    "",
                ]
            )
    lines.extend(["## 输入与来源", ""])
    for role, source in spec.get("inputVersions", {}).items():
        lines.append(f"- {role}：{source['name']}（资料版本：{source['updatedAt']}）")
    lines.extend(["", "## 审核与返修记录", ""])
    for event in value.get("events", []):
        lines.append(f"- {event['createdAt']} · {event['actor']} · {event['message']}")
    return ("\n".join(lines) + "\n").encode()


def concise_report(workflow, spec, value):
    lines = [
        f"# {spec['name']}报告",
        "",
        value.get("answer") or workflow.detail,
    ]
    definition = spec["definitionSnapshot"]
    names = {row["key"]: row["label"] for row in definition["inputRequirements"]}
    inputs = spec.get("inputVersions", {})
    if inputs:
        lines.extend(["", "## 本次资料", ""])
        for role, source in inputs.items():
            lines.append(
                f"- {names.get(role.split(':', 1)[0], role)}：{source['name']}"
            )
    rows = {}
    for node in definition["nodes"]:
        item = value["nodes"][node["id"]]
        for entry in item.get("outputs", {}).get("evidence", []):
            if entry["id"].startswith("output-"):
                rows[entry["id"]] = entry.get("title") or node["title"]
    if rows:
        lines.extend(["", "## 成果", ""])
        lines.extend(f"- {title}（{identity}）" for identity, title in rows.items())
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")
