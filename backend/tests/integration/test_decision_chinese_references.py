"""Repeated Chinese scientific predicates use references without changing content."""

import copy
import json

from apps.agent.decision_budget import project_payload, visible_payload


def test_short_chinese_predicates_deduplicate_by_encoded_size_losslessly():
    condition = (
        "非碳酸盐基岩上的碳酸盐化可能是热液叠加证据，需要岩性与边界测量共同支持。"
    )
    assert len(json.dumps(condition, ensure_ascii=False)) < 64
    assert len(json.dumps(condition, ensure_ascii=False).encode()) > 64
    payload = {
        "knowledge": [
            {
                "id": 1,
                "conditions": [condition, {"threshold": 0.0, "enabled": False}],
                "exceptions": [condition],
                "ruleConfig": {"condition": condition, "parameters": {}},
            }
        ],
        "actualResults": [],
    }
    original = copy.deepcopy(payload)
    projected = project_payload(payload, 1)
    assert condition in projected["contextDefinitions"].values()
    restored = visible_payload(payload, 1)
    assert restored["knowledge"] == payload["knowledge"]
    assert restored["knowledge"][0]["ruleConfig"]["parameters"] == {}
    assert restored["knowledge"][0]["conditions"][1]["enabled"] is False
    assert payload == original
