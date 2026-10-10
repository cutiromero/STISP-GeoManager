"""Stable subject areas, independent of project and permission boundaries."""

import re

from django.core.exceptions import ValidationError
from django.db.models import Count

DOMAINS = {
    "remote_sensing": (
        "遥感基础",
        "传感器、波段、反射率、影像预处理与遥感指数",
    ),
    "pipelines": ("油气管道相关", "油气管道监测、沿线风险、地表变化与安全管理"),
    "geology": ("遥感地质填图逻辑推理", "矿物、岩性、构造与遥感地质证据推理"),
    "arid_ecology": (
        "干旱区生态安全治理",
        "干旱区植被、水资源、荒漠化与生态修复监测",
    ),
}
KEYWORDS = {
    "remote_sensing": (
        "遥感",
        "反射率",
        "波段",
        "传感器",
        "影像",
        "卫星",
        "ndvi",
        "ndwi",
        "ndmi",
        "evi",
        "savi",
        "landsat",
        "sentinel",
        "辐射",
        "大气校正",
        "分辨率",
        "cog",
    ),
    "pipelines": ("管道", "油气", "输油", "输气", "泄漏", "腐蚀", "pipeline"),
    "geology": (
        "地质",
        "填图",
        "矿物",
        "矿产",
        "岩性",
        "岩石",
        "断层",
        "蚀变",
        "构造",
        "mineral",
    ),
    "arid_ecology": (
        "干旱",
        "生态",
        "植被",
        "荒漠",
        "胡杨",
        "ndvi",
        "ndmi",
        "evi",
        "savi",
        "盐渍",
        "水资源",
        "土壤",
        "修复",
        "治理",
        "蒸散",
        "绿度",
    ),
}


def validate_domains(values):
    if (
        not isinstance(values, list)
        or len(values) > 4
        or any(not isinstance(v, str) or v not in DOMAINS for v in values)
    ):
        raise ValidationError("知识分区须为四个可用领域的列表")
    return list(dict.fromkeys(values))


def validate_domain(value):
    if not isinstance(value, str) or value not in DOMAINS:
        raise ValidationError("请选择有效知识分区")
    return value


def query_domains(query):
    text = query.casefold()
    found = [
        domain
        for domain, words in KEYWORDS.items()
        if any(word in text for word in words)
    ]
    return found


def classify_legacy(text):
    """One primary area for legacy material; ambiguous geology remains geology."""
    found = query_domains(text)
    for domain in ("pipelines", "geology", "arid_ecology", "remote_sensing"):
        if domain in found:
            return domain
    return "geology"


def domain_options(entries=None):
    counts = {}
    if entries is not None:
        counts = {
            row["domain"]: row["count"]
            for row in entries.values("domain").annotate(count=Count("id"))
        }
    return [
        {
            "id": key,
            "label": label,
            "description": description,
            "count": counts.get(key, 0),
        }
        for key, (label, description) in DOMAINS.items()
    ]


def search_terms(query):
    """Keep meaningful index names when embedded in a natural-language request."""
    terms = [v.casefold() for v in re.split(r"[\s,，;；、]+", query.strip()) if v]
    for value in re.findall(r"ndvi|ndwi|ndmi|savi|evi|landsat|sentinel", query, re.I):
        if value.casefold() not in terms:
            terms.append(value.casefold())
    return terms
