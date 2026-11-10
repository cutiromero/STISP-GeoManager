"""Rule hints distinguish arbitrary upload fields without bypassing live ACL."""

import csv
import io
import json
import uuid
from copy import deepcopy
from unittest.mock import Mock

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.agent import (
    context,
    generic_mapping,
    geology_generic,
    geology_multi,
    provider,
)
from apps.agent.generic_mapping_context import MappingRuleContextError
from apps.agent.models import AgentWorkflow, WorkflowUpload
from apps.catalog.models import DataResource
from apps.compute.packages import ComputeError
from apps.core.storage import table_data_path
from apps.knowledge.models import KnowledgeEntry
from apps.knowledge.trial_rules import SCENARIO

pytestmark = pytest.mark.django_db
pytest_plugins = ["tests.integration.test_workflow_profile_models"]


def write_rules(env):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=geology_multi.FIELDS)
    writer.writeheader()
    writer.writerows(env["rows"])
    env["path"].write_text(stream.getvalue(), encoding="utf-8")


def set_fields(env, fields):
    upload = WorkflowUpload.objects.get(
        workflow=env["workflow"],
        resource_id=env["workflow"].plan["uploadInputs"]["lithology"],
    )
    upload.profile["fields"] = fields
    upload.save(update_fields=["profile"])
    env["roles"][0]["_profile"] = deepcopy(upload.profile)
    env["roles"][0]["fields"] = [field["name"] for field in fields]


@pytest.fixture
def bound(profiles):
    env = profiles
    entry = KnowledgeEntry.objects.create(
        title="字段样本规则",
        domain="geology",
        status="draft",
        statement="识别名称和代号。",
        rule_config={
            "trialScope": {
                "scenario": SCENARIO,
                "projectId": env["project"].id,
                "ruleId": "L-03",
                "ruleVersion": "0.1",
            },
            "parameters": {"threshold": 0.5},
            "rule": {"id": "L-03"},
        },
    )
    units = {"T3b2": {"name": "八宝山组"}, "O1n1": {"name": "闹仓坚沟组一段"}}
    aliases = {"八宝山组": "T3b2", "闹仓坚沟组一段": "O1n1", "不应发送的词表项": "T3b2"}
    path = table_data_path("mapping/rules.csv")
    path.parent.mkdir(parents=True)
    rules = DataResource.objects.create(
        name="字段任务绑定规则",
        code="geology-multi-rules-mapping",
        data_type="table",
        file_format="CSV",
        storage_path="table/mapping/rules.csv",
        maintainer=env["owner"],
    )
    env = {
        **env,
        "entry": entry,
        "rules": rules,
        "path": path,
        "rows": [
            {
                "rule_id": "L-03",
                "rule_version": "0.1",
                "knowledge_id": entry.id,
                "knowledge_revision": entry.revision,
                "params_json": '{"threshold":0.5}',
                "rule_json": '{"id":"L-03"}',
                "units_json": json.dumps(units, ensure_ascii=False),
                "aliases_json": json.dumps(aliases, ensure_ascii=False),
            }
        ],
    }
    write_rules(env)
    env["workflow"].plan.update(
        rulesResourceId=rules.id, knowledgeSelection={"mode": "auto"}
    )
    env["workflow"].save(update_fields=["plan"])
    return env


def capture(env, monkeypatch, *, selected=None, during_stream=None):
    sent = []
    chosen = selected or env["roles"][0]["fields"][0]

    def stream(model, messages, maximum, guard, **options):
        sent.append(json.loads(messages[1]["content"]))
        if during_stream:
            during_stream()
        yield json.dumps(
            {"roles": {"lithology": {"name": {"field": chosen, "reason": "参考样本"}}}}
        )

    monkeypatch.setattr(provider, "stream", stream)
    return sent


def infer(env):
    return generic_mapping.model_targets(env["workflow"], env["policy"], env["roles"])


@pytest.fixture
def derived_bound(bound):
    workflow = bound["workflow"]
    derived = DataResource.objects.create(
        name="已适配的工作资料",
        code="derived-mapping-profile",
        data_type="vector",
        owner_only=True,
        maintainer=bound["owner"],
        source=f"workflow-working:{workflow.pk}:input-adapter:lithology",
    )
    profile = {
        "kind": "vector",
        "crs": "EPSG:32646",
        "featureCount": 2,
        "geometryTypes": ["Polygon"],
        "fields": [{"name": "derived_name", "type": "text", "samples": ["八宝山组"]}],
    }
    workflow.plan["effectiveInputs"] = {"lithology": derived.pk}
    workflow.plan["preparedInputProfiles"] = {
        str(derived.pk) + ":" + derived.updated_at.isoformat(): profile
    }
    workflow.resource_ids.append(derived.pk)
    workflow.save(update_fields=["plan", "resource_ids"])
    roles = deepcopy(bound["roles"])
    roles[0].update(resourceId=derived.pk, _profile=profile, fields=["derived_name"])
    for target in roles[0]["targets"]:
        target["field"] = "derived_name" if target["key"] == "name" else None
    return {**bound, "roles": roles, "derived": derived}


def test_mapping_uses_the_frozen_derived_profile_without_reopening_files(
    derived_bound, monkeypatch
):
    from apps.agent import workflow_uploads

    reader = Mock(
        side_effect=AssertionError(
            "The streaming guard must reuse its version-bound profile"
        )
    )
    monkeypatch.setattr(workflow_uploads, "catalog_profile", reader)
    sent = capture(derived_bound, monkeypatch, selected="derived_name")
    result = infer(derived_bound)
    assert result["lithology"]["name"]["field"] == "derived_name"
    assert sent[0]["roles"]["lithology"]["fields"][0]["name"] == "derived_name"
    reader.assert_not_called()


@pytest.mark.parametrize(
    "change",
    ["derived_revision", "source_profile", "binding", "cached_profile", "derived_acl"],
)
def test_mapping_still_rejects_source_or_derived_changes_during_stream(
    derived_bound, monkeypatch, change
):
    env = derived_bound

    def mutate():
        current = AgentWorkflow.objects.get(pk=env["workflow"].pk)
        if change == "derived_revision":
            env["derived"].description = "Changed"
            env["derived"].save()
        elif change == "source_profile":
            upload = WorkflowUpload.objects.get(workflow=current)
            upload.profile["fields"][0]["samples"] = ["Changed"]
            upload.save(update_fields=["profile"])
        elif change == "binding":
            current.plan["effectiveInputs"] = {}
            current.save(update_fields=["plan"])
        elif change == "cached_profile":
            current.plan["preparedInputProfiles"] = {}
            current.save(update_fields=["plan"])
        else:
            env["derived"].maintainer = env["outsider"]
            env["derived"].save(update_fields=["maintainer"])

    capture(env, monkeypatch, selected="derived_name", during_stream=mutate)
    with pytest.raises(PermissionDenied):
        infer(env)


def test_arbitrary_fields_distinguish_strata_places_codes_and_keep_model_choice(
    bound, monkeypatch
):
    names = ["f_" + uuid.uuid4().hex for _ in range(4)]
    set_fields(
        bound,
        [
            {"name": names[0], "type": "text", "samples": ["八宝山镇", "闹仓坚沟村"]},
            {
                "name": names[1],
                "type": "text",
                "samples": ["八宝山组", "闹仓坚沟组一段"],
            },
            {"name": names[2], "type": "text", "samples": ["T3b2", "O1n1"]},
            {
                "name": names[3],
                "type": "text",
                "samples": ["八宝山组", "闹仓坚沟组一段"],
            },
        ],
    )
    # Either semantically equivalent name column is still the model's choice.
    sent = capture(bound, monkeypatch, selected=names[3])
    result = infer(bound)
    fields = {
        field["name"]: field["ruleSampleMatches"]
        for field in sent[0]["roles"]["lithology"]["fields"]
    }
    assert fields[names[0]]["aliasExactSampleCount"] == 0
    assert fields[names[1]]["aliasExactSampleCount"] == 2
    assert fields[names[2]]["unitCodeExactSampleCount"] == 2
    assert fields[names[3]]["untruncatedAliasMatchCount"] == 2
    assert result["lithology"]["name"]["field"] == names[3]
    assert "不应发送的词表项" not in json.dumps(sent, ensure_ascii=False)
    assert "rulesResourceId" not in sent[0]
    sent = capture(bound, monkeypatch, selected=names[0])
    assert infer(bound)["lithology"]["name"]["field"] == names[0]


def test_no_bound_rules_keeps_legacy_payload_without_rule_reads(profiles, monkeypatch):
    reader = Mock(side_effect=AssertionError("must not read rules"))
    monkeypatch.setattr(geology_multi, "read_rules", reader)
    sent = capture(profiles, monkeypatch)
    infer(profiles)
    assert "ruleContext" not in sent[0]
    assert "ruleSampleMatches" not in sent[0]["roles"]["lithology"]["fields"][0]
    reader.assert_not_called()


def test_displayed_samples_are_bounded_and_truncation_is_not_full_value_evidence(
    bound, monkeypatch
):
    value = "长" * 80
    aliases = json.loads(bound["rows"][0]["aliases_json"])
    aliases[value] = "T3b2"
    bound["rows"][0]["aliases_json"] = json.dumps(aliases)
    write_rules(bound)
    set_fields(
        bound,
        [
            {
                "name": "x",
                "type": "text",
                "samples": [value + "后缀", "八宝山组"] + ["未知"] * 10,
                "distinctCount": 999,
            },
            {"name": "empty", "type": "text", "samples": [], "distinctCount": 0},
        ],
    )
    sent = capture(bound, monkeypatch)
    infer(bound)
    fields = sent[0]["roles"]["lithology"]["fields"]
    assert len(fields[0]["samples"]) == 8 and fields[0]["samples"][0] == value
    stats = fields[0]["ruleSampleMatches"]
    assert stats["sampleCount"] == 8 and stats["possiblyTruncatedSampleCount"] == 1
    assert (
        stats["aliasExactSampleCount"] == 2 and stats["untruncatedAliasMatchCount"] == 1
    )
    assert fields[1]["ruleSampleMatches"]["sampleCount"] == 0
    summary = sent[0]["ruleContext"]
    assert summary["scope"] == "displayed_profile_samples"
    assert summary["profileRowLimit"] == 1000 and summary["maxSampleCharacters"] == 80
    assert (
        "未命中不能推断" in summary["limitation"]
        and "计数不是行数" in summary["limitation"]
    )


@pytest.mark.parametrize("confirmed", [False, True])
def test_user_units_can_override_default_vocabulary_only_after_confirmation(
    bound, monkeypatch, confirmed
):
    workflow = bound["workflow"]
    resource = DataResource.objects.create(
        name="用户单位表",
        code="mapping-user-units",
        data_type="table",
        maintainer=bound["owner"],
        owner_only=True,
        source="workflow-upload:" + workflow.plan["uploadBatchId"],
    )
    WorkflowUpload.objects.create(
        owner=bound["owner"],
        resource=resource,
        workflow=workflow,
        batch_id=workflow.plan["uploadBatchId"],
        file_name="units.csv",
        profile={"fields": [{"name": "u", "type": "text", "samples": ["用户单元"]}]},
    )
    workflow.plan["uploadInputs"]["units"] = resource.id
    if confirmed:
        workflow.plan["unitOverrides"] = {
            "units": {"U": {"name": "用户单元"}},
            "aliases": {"用户单元": "U", "八宝山组": "U"},
        }
    workflow.save(update_fields=["plan"])
    set_fields(
        bound, [{"name": "x", "type": "text", "samples": ["用户单元", "U", "八宝山组"]}]
    )
    sent = capture(bound, monkeypatch)
    infer(bound)
    summary = sent[0]["ruleContext"]
    assert summary["userUnitsStatus"] == (
        "confirmed_override" if confirmed else "pending_confirmation"
    )
    assert "可覆盖默认词表" in summary["limitation"]
    stats = sent[0]["roles"]["lithology"]["fields"][0]["ruleSampleMatches"]
    assert stats["aliasExactSampleCount"] == (2 if confirmed else 1)
    assert stats["unitCodeExactSampleCount"] == (1 if confirmed else 0)


def test_initial_rule_read_is_inside_guard_and_after_budget_authorization(
    bound, monkeypatch
):
    from apps.agent import workflow as workflow_module

    actual = workflow_module._authorize
    calls = []

    def tightened(workflow):
        user, policy = actual(workflow)
        calls.append(1)
        return user, {**policy, "maxOutputTokens": 1} if len(calls) > 1 else policy

    reader = Mock(side_effect=AssertionError("budget must reject before rules"))
    monkeypatch.setattr(workflow_module, "_authorize", tightened)
    monkeypatch.setattr(geology_multi, "read_rules", reader)
    with pytest.raises(PermissionDenied, match="预算"):
        infer(bound)
    reader.assert_not_called()
    assert not bound["requests"]


def test_initial_rule_read_runs_with_guard_discovery_scope(bound, monkeypatch):
    from apps.agent.resource_discovery import _INTERNAL_SCOPE

    reader = geology_multi.read_rules
    calls = []

    def guarded(*args, **options):
        assert _INTERNAL_SCOPE.get() is not None
        calls.append(options["workflow"].pk)
        return reader(*args, **options)

    monkeypatch.setattr(geology_multi, "read_rules", guarded)
    infer(bound)
    assert len(calls) >= 3 and set(calls) == {bound["workflow"].pk}


def test_rule_context_stays_subject_to_token_budget(bound, monkeypatch):
    monkeypatch.setattr(context, "count_tokens", lambda *args: 8000)
    with pytest.raises(ComputeError, match="token"):
        infer(bound)
    assert not bound["requests"]


@pytest.mark.parametrize(
    "change",
    [
        "rule_id",
        "selection",
        "overrides",
        "profile",
        "resource",
        "rules",
        "raw_params",
        "knowledge",
        "rule_acl",
        "knowledge_acl",
        "upload_acl",
    ],
)
def test_context_changes_and_acl_revocation_stop_results(bound, monkeypatch, change):
    def mutate():
        workflow = AgentWorkflow.objects.get(pk=bound["workflow"].pk)
        if change in {"rule_id", "selection", "overrides"}:
            key, value = {
                "rule_id": ("rulesResourceId", bound["rules"].id + 10000),
                "selection": ("knowledgeSelection", {"mode": "none"}),
                "overrides": ("unitOverrides", {"units": {"U": {}}}),
            }[change]
            workflow.plan[key] = value
            workflow.save(update_fields=["plan"])
        elif change == "profile":
            upload = WorkflowUpload.objects.get(workflow=workflow)
            upload.profile["fields"][0]["samples"] = ["已变化"]
            upload.save(update_fields=["profile"])
        elif change == "resource":
            DataResource.objects.filter(
                pk=workflow.plan["uploadInputs"]["lithology"]
            ).update(updated_at=timezone.now())
        elif change in {"rules", "raw_params"}:
            key = "aliases_json" if change == "rules" else "params_json"
            bound["rows"][0][key] = (
                '{"新名称":"T3b2"}' if change == "rules" else '{"threshold":0.9}'
            )
            write_rules(bound)
        elif change == "knowledge":
            KnowledgeEntry.objects.filter(pk=bound["entry"].pk).update(
                statement="正文原地变化"
            )
        elif change == "rule_acl":
            DataResource.objects.filter(pk=bound["rules"].pk).update(status="inactive")
        elif change == "upload_acl":
            DataResource.objects.filter(
                pk=workflow.plan["uploadInputs"]["lithology"]
            ).update(status="inactive")
        else:
            KnowledgeEntry.objects.filter(pk=bound["entry"].pk).update(status="retired")

    capture(bound, monkeypatch, during_stream=mutate)
    with pytest.raises(PermissionDenied):
        infer(bound)


@pytest.mark.parametrize("failure", ["invalid", "missing", "acl", "disabled_knowledge"])
def test_bound_rule_failure_never_silently_falls_back(bound, monkeypatch, failure):
    if failure == "invalid":
        bound["rows"][0]["aliases_json"] = "invalid-json"
        write_rules(bound)
    elif failure == "missing":
        bound["path"].unlink()
    elif failure == "acl":
        bound["rules"].status = "inactive"
        bound["rules"].save(update_fields=["status"])
    else:
        bound["workflow"].plan["knowledgeSelection"] = {"mode": "none"}
        bound["workflow"].save(update_fields=["plan"])
    expected = (
        MappingRuleContextError
        if failure in {"invalid", "missing"}
        else PermissionDenied
    )
    with pytest.raises(expected):
        geology_generic.propose_mapping(
            bound["workflow"], bound["owner"], bound["policy"]
        )
    assert not bound["requests"]
