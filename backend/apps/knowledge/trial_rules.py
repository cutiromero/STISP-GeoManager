"""Explicit, project/scenario-bound draft rules; ordinary retrieval stays unchanged."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from django.core.exceptions import PermissionDenied

from apps.compute.packages import ComputeError
from .models import KnowledgeEntry, KnowledgeRevision
from .services import require_project, serialize

SCENARIO = "geology_multi_element_reasoning"


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def read_bound_rules(
    user, project_id, scenario, bindings, *, expected=None, history=False
):
    """No search or draft enumeration: every requested ID and revision is explicit."""
    if require_project(user) != project_id or scenario != SCENARIO:
        raise PermissionDenied("试用规则只允许在其绑定的项目和演示场景读取")
    if not isinstance(bindings, list) or not 1 <= len(bindings) <= 40:
        raise ComputeError("请显式绑定本案例试用规则及其版本")
    entries, seen, seen_rules = [], set(), set()
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != {
            "id",
            "revision",
            "ruleId",
            "ruleVersion",
        }:
            raise ComputeError("试用知识绑定须包含条目、修订、规则编号和版本")
        identity, revision = binding["id"], binding["revision"]
        if type(identity) is not int or type(revision) is not int or identity in seen:
            raise ComputeError("试用知识编号或修订无效、重复")
        if (
            any(
                not isinstance(binding[key], str) or not 1 <= len(binding[key]) <= 80
                for key in ("ruleId", "ruleVersion")
            )
            or binding["ruleId"] in seen_rules
        ):
            raise ComputeError("试用规则编号或版本无效、重复")
        seen.add(identity)
        seen_rules.add(binding["ruleId"])
        query = KnowledgeEntry._base_manager.filter(
            pk=identity,
            project_tag_id=project_id,
            domain="geology",
        )
        entry = query.first()
        if entry is None:
            raise PermissionDenied("绑定的本案例试用知识已变化、停用或不属于当前项目")
        value = serialize(entry)
        if not history:
            if value.get("revision") != revision:
                from .formal_rules import published_predecessor

                value = published_predecessor(entry, value, revision)
                if value is None:
                    raise PermissionDenied("绑定的项目知识已变化，请重新生成计划")
            if value.get("status") not in {"draft", "published"}:
                raise PermissionDenied("绑定的项目知识已停用")
        if history:
            prior = KnowledgeRevision._base_manager.filter(
                entry_id=identity, project_tag_id=project_id, revision=revision
            ).first()
            if prior:
                value = deepcopy(prior.snapshot)
            if (
                value.get("id") != identity
                or value.get("revision") != revision
                or value.get("projectTagId") != project_id
                or value.get("domain") != "geology"
                or value.get("status") not in {"draft", "published"}
            ):
                raise PermissionDenied("已保存的本案例知识修订不属于当前历史记录")
        config = value.get("ruleConfig")
        if not isinstance(config, dict):
            raise ComputeError("试用知识缺少有效场景绑定")
        scope = config.get("trialScope", {})
        if scope != {
            "scenario": scenario,
            "projectId": project_id,
            "ruleId": binding["ruleId"],
            "ruleVersion": binding["ruleVersion"],
        }:
            raise PermissionDenied("试用知识的项目、场景或规则版本绑定不一致")
        parameters = config.get("parameters")
        rule = config.get("rule")
        if not isinstance(parameters, dict) or not isinstance(rule, dict):
            raise ComputeError("试用知识缺少可执行参数或规则条件")
        value["trialBinding"] = {
            **binding,
            "scope": "项目正式规则"
            if value.get("status") == "published"
            else "本案例试用",
        }
        entries.append(value)
    if expected is not None and digest(entries) != expected:
        raise PermissionDenied("试用知识正文、适用条件或参数已变化，请重新生成计划")
    return entries


def authorize_trial_evidence(workflow, user, *, history=False):
    """Validate the exact frozen set before continuation, approval and history reads."""
    bindings = workflow.plan.get("trialRuleBindings", [])
    if not bindings:
        return set()
    entries = read_bound_rules(
        user,
        workflow.project_tag_id,
        # The generic upload workflow runs the same bound multi-element rule set.
        SCENARIO
        if workflow.workflow_type == "geology_generic"
        else workflow.workflow_type,
        [
            {key: item[key] for key in ("id", "revision", "ruleId", "ruleVersion")}
            for item in bindings
        ],
        expected=workflow.plan.get("trialRulesDigest"),
        history=history,
    )
    recorded = {
        item["id"]: item for item in workflow.evidence if item.get("trialBinding")
    }
    if recorded != {item["id"]: item for item in entries}:
        raise PermissionDenied("已保存的试用知识引用与当前绑定不一致")
    return set(recorded)
