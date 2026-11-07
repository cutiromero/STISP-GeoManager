"""Explicit semantics for the corrected-only, structure-led prospect operator."""

from copy import deepcopy

METHOD = "weighted_neighborhood_presence_v2"
VERSION = "2026-11-07-neighborhood"
RESOURCE_CODE = "geology-multi-rules-prospect-v2"
CONDITION = (
    "仅在修正后资料中圈区。每种矿物在分析网格内取有效识别像元的最大批准权重，"
    "再取search_m圆形格网中心邻域内的最大权重；每种矿物只计一次，"
    "累加达到min_types才满足蚀变组合。必须同时位于有效构造支持范围及已知基岩岩性内；"
    "优先保留邻域组合更强、有利岩性支持更多的少量目标。"
    "四邻域连通圈区，过小或过大连通区不作为目标，数量不超过max_zone_count。"
    "邻域组合为网格近似，不等同于同像元矿物共存；结果为调查线索，不表示已证实矿化或矿化概率。"
)


def revised_rule(previous):
    rule = deepcopy(previous)
    rule.update(
        version=VERSION,
        condition=CONDITION,
        action="形成少量修正后优先核查目标及逐区依据",
    )
    rule["params"] = {**rule.get("params", {}), "evidence_method": METHOD}
    rule["basis"] = {
        **rule.get("basis", {}),
        "statement": CONDITION,
        "gap": "邻域距离、最小组合数及圈区尺度为项目分析参数，需结合区域地质和后续调查核查；原引用不证明当前区域已成矿。",
    }
    return rule
