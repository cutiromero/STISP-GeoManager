from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from apps.knowledge.formal_rules import published_predecessor, semantics


def test_publication_can_preserve_exact_frozen_semantics_without_rewriting_history():
    old = {
        "id": 1,
        "projectTagId": 3,
        "domain": "geology",
        "title": "规则（本案例试用）",
        "revision": 1,
        "status": "draft",
        "statement": "根据实际面积检查",
        "conditions": ["小于阈值"],
        "exceptions": ["边界"],
        "sources": [{"title": "资料"}],
        "ruleConfig": {"trialScope": {"projectId": 3}, "parameters": {"threshold": 10}},
    }
    current = deepcopy(old)
    current.update(title="项目地质规则", revision=2, status="published")
    current["ruleConfig"]["formalRelease"] = {"previousRevision": 1}
    with patch("apps.knowledge.formal_rules.KnowledgeRevision") as model:
        model._base_manager.filter.return_value.first.return_value = SimpleNamespace(
            snapshot=old
        )
        value = published_predecessor(
            SimpleNamespace(id=1, project_tag_id=3), current, 1
        )
        assert value == old and value is not old
        current["ruleConfig"]["parameters"]["threshold"] = 99
        assert (
            published_predecessor(SimpleNamespace(id=1, project_tag_id=3), current, 1)
            is None
        )
    assert old["status"] == "draft"


def test_conditions_and_sources_are_semantics_not_cosmetic_metadata():
    before = {
        "statement": "规则",
        "conditions": ["A"],
        "sources": ["document"],
        "ruleConfig": {},
    }
    after = {**before, "conditions": ["B"]}
    assert semantics(before) != semantics(after)
