"""Budget views must retain executable predicates and respect stage evidence."""

import copy
import hashlib

import pytest

from apps.agent.decision_budget import dumps, project_payload, visible_payload


def packet(action="geology-multi-check"):
    knowledge = []
    for index, rule in enumerate(("L-01", "P-02", "FUTURE-01"), 1):
        knowledge.append(
            {
                "id": index,
                "revision": 7,
                "status": "draft",
                "title": rule,
                "statement": "仅在实测包围条件满足时形成疑点；不等于已证明错误。",
                "explanation": "说明和来源原文留在完整审计。" * 100,
                "sources": [{"title": "来源原文", "excerpt": "完整来源" * 100}],
                "conditions": [
                    "地区和投影必须一致",
                    {"sameAs": f"knowledge[{index - 1}].statement"},
                ],
                "exceptions": ["构造窗、捕虏体、缺失观测必须保留待裁定"],
                "trialBinding": {"ruleId": rule, "ruleVersion": "trial-7"},
                "ruleConfig": {
                    "parameters": {"ratio": 0.95},
                    "rule": {
                        "condition": {
                            "all": [{"area": {"lt": 500}}, {"ratio": {"gte": 0.95}}]
                        },
                        "basis": {"statement": "明确的地质依据", "gap": "尚缺现场验证"},
                        "action": "request_review",
                    },
                },
            }
        )
    return {
        "allowedAction": action,
        "knowledge": knowledge,
        "availableEvidence": [{"kind": "knowledge", "id": str(i)} for i in (1, 2, 3)]
        + [{"kind": "output", "id": "99"}],
        "allowedAlgorithm": {
            "versionId": 71,
            "checksum": "a" * 64,
            "manifest": {
                "identifier": action,
                "runtime": "python-geospatial-v1",
                "inputs": [
                    {
                        "key": "lithology",
                        "kind": "vector",
                        "geometryTypes": ["Polygon"],
                        "required": True,
                        "label": "岩性",
                    }
                ],
                "parameters": [{"key": "ratio", "type": "number", "min": 0, "max": 1}],
                "outputs": [{"key": "issues", "kind": "table", "file": "issues.csv"}],
            },
        },
    }


@pytest.mark.parametrize("level", (3, 4))
def test_execution_view_keeps_exact_predicates_versions_and_unknown_rules(level):
    source = packet()
    original = copy.deepcopy(source)
    projected = project_payload(source, level)
    visible = visible_payload(source, level)
    assert source == original
    assert [entry["id"] for entry in visible["knowledge"]] == [1, 3]
    for entry, old in zip(
        visible["knowledge"],
        (source["knowledge"][0], source["knowledge"][2]),
        strict=True,
    ):
        for key in (
            "id",
            "revision",
            "status",
            "exceptions",
            "ruleConfig",
            "trialBinding",
        ):
            assert entry[key] == old[key]
        assert entry["conditions"] == [old["conditions"][0], old["statement"]]
        assert entry["explanation"] == "" and "sources" not in entry
    assert visible["availableEvidence"] == [
        source["availableEvidence"][i] for i in (0, 2, 3)
    ]
    audit = visible["knowledgeProjection"]
    assert audit["sourceCount"] == 3 and audit["shownCount"] == 2
    assert (
        audit["sourceSha256"]
        == hashlib.sha256(dumps(source["knowledge"]).encode()).hexdigest()
    )
    assert audit["deferred"] == [
        {"id": 2, "revision": 7, "ruleId": "P-02", "reason": "later_prospect_stage"}
    ]
    assert len(dumps(projected)) < len(dumps(source))
    algorithm = visible["allowedAlgorithm"]
    assert algorithm["checksum"] == source["allowedAlgorithm"]["checksum"]
    assert (
        algorithm["manifest"]["parameters"]
        == source["allowedAlgorithm"]["manifest"]["parameters"]
    )
    assert algorithm["manifest"]["inputs"][0]["geometryTypes"] == ["Polygon"]


def test_prospect_stage_retains_its_rules_and_unstructured_explanations():
    source = packet("geology-multi-prospect")
    source["knowledge"].append(
        {
            "id": 4,
            "revision": 1,
            "statement": "公开解释",
            "explanation": "独立解释不能因没有结构化规则而消失",
            "conditions": ["公开条件"],
            "exceptions": ["公开例外"],
        }
    )
    source["availableEvidence"].append({"kind": "knowledge", "id": "4"})
    visible = visible_payload(source, 4)
    assert [entry["id"] for entry in visible["knowledge"]] == [1, 2, 3, 4]
    assert (
        visible["knowledge"][-1]["explanation"]
        == source["knowledge"][-1]["explanation"]
    )
    assert visible["knowledgeProjection"]["deferred"] == []


@pytest.mark.parametrize("level", (0, 1, 2))
def test_gentle_projection_does_not_defer_rules_or_drop_source_metadata(level):
    visible = visible_payload(packet(), level)
    assert len(visible["knowledge"]) == 3
    assert all(entry["sources"] for entry in visible["knowledge"])
    assert "knowledgeProjection" not in visible
