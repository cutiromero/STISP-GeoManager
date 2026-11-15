"""Human-readable domain output titles, independent of file paths and task IDs."""

# CONFIGURATION
RF_TITLES = {
    "classification": "互花米草分布",
    "probability": "互花米草分布概率",
    "statistics": "互花米草面积统计",
    "original": "解译参考影像",
    "manifest": "互花米草处理记录",
}
FIRE_TITLES = {
    "observation": "火烧面积",
    "classification": "火烧面积分级",
    "statistics": "火烧面积统计",
    "series": "火烧面积时序统计",
    "manifest": "野火处理记录",
}


def output_title(output):
    identifier = output.task.version.algorithm.identifier
    facts = output.metadata.get("knowledgeFacts") or {}
    if identifier == "spartina-rf-infer":
        value = facts.get("spartina") or {}
        periods = value.get("inputPeriods") or []
        period = (
            "至".join([periods[0], periods[-1]])
            if len(periods) > 1
            else periods[0]
            if periods
            else ""
        )
        if output.key == "original" and len(periods) > 1:
            period = periods[1]
        title = RF_TITLES.get(output.key, output.label)
    elif identifier == "wildfire-observe":
        value = facts.get("wildfireObservation") or {}
        current = value.get("current") or {}
        period = (
            (current.get("observedStart") or "")[:7]
            if value.get("periodMode") == "monthly"
            else current.get("observedStart") or ""
        )
        if output.key == "series" and value.get("series"):
            first = value["series"][0]["observedStart"][:7]
            last = value["series"][-1]["observedEnd"][:7]
            period = first if first == last else first + "至" + last
        title = FIRE_TITLES.get(output.key, output.label)
        if value.get("unit") != "ha":
            title = title.replace("火烧面积", "火辐射功率")
    else:
        return None
    return f"{title}（{period}）" if period else title
