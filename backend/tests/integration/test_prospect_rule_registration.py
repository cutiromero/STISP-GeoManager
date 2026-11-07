"""The new rule packet never changes an old knowledge entry or bound input."""

# ruff: noqa: F811
import json
import pytest


from apps.agent.management.commands.register_prospect_rules import Command
from apps.catalog.models import DataResource
from apps.core.storage import table_data_path
from apps.knowledge.models import KnowledgeEntry
from apps.knowledge.prospect_rules import METHOD, RESOURCE_CODE
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo  # noqa: F401
from tests.integration.test_geology_multi_workflow import multi  # noqa: F401


pytestmark = pytest.mark.django_db


def test_rule_registration_keeps_predecessor_and_is_idempotent(multi, monkeypatch):
    import pandas as pd
    from apps.agent.geology_multi import FIELDS
    from apps.knowledge.services import serialize

    old = KnowledgeEntry.objects.create(
        title="P-02 原组合",
        statement="覆盖比例",
        status="published",
        rule_config={
            "trialScope": {
                "scenario": "geology_multi_element_reasoning",
                "projectId": multi["project"].id,
                "ruleId": "P-02",
                "ruleVersion": "old",
            },
            "parameters": {"min_types": 2, "search_m": 250},
            "rule": {"id": "P-02", "params": {"min_types": 2, "search_m": 250}},
        },
    )
    original = serialize(old)
    row = dict.fromkeys(FIELDS, "") | {
        "rule_id": "P-02",
        "rule_version": "old",
        "knowledge_id": str(old.id),
        "knowledge_revision": "1",
        "params_json": json.dumps(old.rule_config["parameters"]),
        "rule_json": json.dumps(old.rule_config["rule"]),
        "units_json": '{"C":{"category":"stratum"}}',
        "aliases_json": '{"carbonate":"C"}',
    }
    source = DataResource.objects.create(
        name="原规则",
        code="geology-multi-rules-old",
        data_type="table",
        maintainer=multi["owner"],
    )
    monkeypatch.setattr(
        "apps.agent.management.commands.register_prospect_rules.frame",
        lambda resource: (pd.DataFrame([row]), {"scope": "all"}),
    )
    monkeypatch.setattr(
        "apps.agent.management.commands.register_prospect_rules.read_bound_rules",
        lambda *args: [original | {"trialBinding": {"ruleId": "P-02"}}],
    )
    command = Command()
    monkeypatch.setattr(
        "apps.agent.management.commands.register_prospect_rules.is_superadmin",
        lambda actor: actor.pk == multi["owner"].pk,
    )
    command.handle(rules_resource=source.pk, actor=multi["owner"].pk, apply=False)
    command.register(source, multi["owner"], True)
    resource = DataResource.objects.get(code=RESOURCE_CODE)
    path = table_data_path(resource.storage_path.removeprefix("table/"))
    content = path.read_bytes()
    old.refresh_from_db()
    assert serialize(old) == original
    assert (
        KnowledgeEntry.objects.get(
            seed_key="geology-multi-P-02-prospect-v2"
        ).rule_config["parameters"]["evidence_method"]
        == METHOD
    )
    command.register(source, multi["owner"], True)
    assert DataResource.objects.filter(code=RESOURCE_CODE).count() == 1
    assert path.read_bytes() == content
