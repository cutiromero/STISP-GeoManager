"""Deterministic request projections; the complete source stays in stage audit."""

import copy
import hashlib
import json
import math
import re
from collections import Counter

from .demo_execution_evidence import (
    QUALITY_KEYS,
    execution_evidence_scope,
    execution_fact_paths,
    project_execution_evidence,
)


MAX_LEVEL = 4
ROW_LIMITS = (40, 30, 20, 10, 5)
GROUP_LIMITS = (96, 80, 64, 48, 24)
BOUNDED_LISTS = {
    "rows",
    "groups",
    "addedEvidence",
    "suggestions",
    "repairableAttributeRows",
    "issueKnowledgeRequirements",
    "byPhaseAndGrade",
    "evidenceCombinations",
}
REFERENCE_NOTE = (
    "contextDefinitions中的编号由{$ref:编号}引用，须按原值展开理解。"
    "知识正文可能为节选，编号、修订、适用条件、例外和结构化规则保留；"
    "不能从未展示的正文推断依据，证据不足须request_review。"
    "分组count及measurementRanges为完整快照统计，不是代表样本的统计。"
    "evidenceProjection记录完整输入总数、源签名及展示行位置；省略项未被模型审阅。"
    "完整输入统计仅覆盖已读取集合；sourceScope或readingScope为prefix_sample时不能推断整个数据集。"
    "代表样本只能支持已展示对象，不能代替整组适用条件及例外的核查。"
)


class BudgetReviewRequired(Exception):
    pass


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _expand_knowledge(payload):
    def expand(value):
        if isinstance(value, dict):
            if set(value) == {"sameAs"} and isinstance(value["sameAs"], str):
                target = payload
                for name, index in re.findall(r"([\w]+)|\[(\d+)\]", value["sameAs"]):
                    target = target[name] if name else target[int(index)]
                return expand(target)
            return {key: expand(item) for key, item in value.items()}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value

    expanded = copy.deepcopy(payload)
    expanded["knowledge"] = expand(payload.get("knowledge", []))
    return expanded


def _deduplicate(payload):
    counts = Counter()

    def count(value):
        if isinstance(value, (dict, list, str)):
            signature = dumps(value)
            if len(signature.encode("utf-8")) >= 64:
                counts[signature] += 1
        if isinstance(value, dict):
            for item in value.values():
                count(item)
        elif isinstance(value, list):
            for item in value:
                count(item)

    count(payload)
    definitions, identities = {}, {}

    def project(value, *, definition=False):
        if not definition and isinstance(value, (dict, list, str)):
            signature = dumps(value)
            if counts[signature] > 1:
                if signature not in identities:
                    identity = f"r{len(identities) + 1}"
                    identities[signature] = identity
                    definitions[identity] = project(value, definition=True)
                return {"$ref": identities[signature]}
        if isinstance(value, dict):
            return {key: project(item) for key, item in value.items()}
        if isinstance(value, list):
            return [project(item) for item in value]
        return value

    projected = project(payload, definition=True)
    projected["contextDefinitions"] = definitions
    projected["contextProjectionNote"] = (
        "contextDefinitions中的$ref按原值展开。仅审阅完整本批成员；省略材料未审阅，不能据此补造结论。"
        if payload.get("modelBatch", {}).get("completeMembers")
        else REFERENCE_NOTE
    )
    return projected


def _summary(value, limit):
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…（节选）"
    if isinstance(value, list):
        return [_summary(item, limit) for item in value]
    if isinstance(value, dict):
        return {key: _summary(item, limit) for key, item in value.items()}
    return value


def _history(value):
    if not isinstance(value, dict):
        return value
    return {
        key: _summary(item, 320)
        for key, item in value.items()
        if key
        in {
            "workflowId",
            "oldDecision",
            "judgement",
            "resultSummary",
            "nextAction",
            "evidenceRefs",
            "actualResultOutputIds",
            "oldContextChecksum",
            "newContextChecksum",
            "addedEvidence",
        }
    }


def _number(value):
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _execution_batch_evidence(payload, level):
    """A review batch needs its members, totals and quality, not map render headers."""
    if (
        level < 2
        or payload.get("allowedAction") != "geology-multi-apply"
        or not payload.get("modelBatch", {}).get("completeMembers")
    ):
        return payload
    results = payload.get("actualResults", [])
    source_sha = hashlib.sha256(dumps(results).encode()).hexdigest()
    reference_only, references, details, rules = [], [], [], set()
    detail_keys = {"issues", "statistics", "alteration_quality"}
    for result in results:
        for group in result.get("groups", []):
            rules.add(group.get("rule_id"))
        metadata = result.get("metadata", {})
        # Keep real quality failures/warnings; schema, map dimensions and
        # duplicate quality references are available in the original artifact.
        quality = {
            key: value
            for key, value in metadata.items()
            if key
            in {
                "qualityCheck",
                "qualityCheckRef",
                "quality",
                "validation",
                "warning",
                "warnings",
                "error",
                "errors",
                "status",
            }
        }
        result["metadata"] = quality
        result.pop("samplingNote", None)
        if result.get("key") in detail_keys:
            result.pop("countsByRule", None)
            if result["key"] == "issues":
                result.pop("columns", None)
            columns, rows = result.get("columns", []), result.get("rows", [])
            if (
                columns
                and rows
                and all(
                    isinstance(row, dict) and set(row) == set(columns) for row in rows
                )
            ):
                result["rows"] = [[row[name] for name in columns] for row in rows]
                result["rowFormat"] = "columns"
            details.append(result)
            continue
        reference_only.append(result["outputId"])
        independent_quality = {
            key: value for key, value in quality.items() if key != "qualityCheckRef"
        }
        if independent_quality:
            references.append(
                {"outputId": result["outputId"], "quality": independent_quality}
            )
    payload["actualResults"] = details
    task = payload.get("editTask")
    if isinstance(task, dict) and "issueRuleKnowledge" in task:
        task["issueRuleKnowledge"] = [
            entry
            for entry in task["issueRuleKnowledge"]
            if entry.get("ruleId") in rules
        ]
    omitted_ids = {str(identity) for identity in reference_only}
    payload["availableEvidence"] = [
        {key: value for key, value in ref.items() if key != "title"}
        for ref in payload.get("availableEvidence", [])
        if ref["kind"] != "output" or str(ref["id"]) not in omitted_ids
    ]
    payload["batchEvidenceProjection"] = {
        "sourceSha256": source_sha,
        "referenceOnlyOutputIds": reference_only,
        "referenceArtifactQuality": references,
        "referenceScope": "identity_and_quality_only",
        "note": (
            "本批issues保留全部本批成员及原始测量，statistics和alteration_quality保留全部已读取行。"
            "其余图层、栅格头与重复蚀变汇总仅列身份，完整清单由sourceSha256绑定，不能作为内容证据；"
            "完整文件和元数据保存在原始审计。蚀变逐单元判断依据本批issues测量，"
            "其他批次尚未审阅。issueRuleKnowledge仅列本批规则，不改变原始规则绑定。"
        ),
    }
    for role in payload.get("inputRoles", []):
        metadata = role.get("metadata")
        if isinstance(metadata, dict):
            role["metadata"] = {
                key: value
                for key, value in metadata.items()
                if key in {"fields", "crs", "geometryTypes", "warnings", "qualityCheck"}
            }
    role_versions = {
        role["role"]: {
            "resourceId": role.get("resourceId"),
            "revision": role.get("revision"),
        }
        for role in payload.get("inputRoles", [])
        if role.get("role")
    }
    versions = payload.get("upstreamVersions", {})
    if isinstance(versions, dict):
        payload["upstreamVersions"] = {
            role: value
            for role, value in versions.items()
            if value != role_versions.get(role)
        }
        if len(payload["upstreamVersions"]) != len(versions):
            payload["batchEvidenceProjection"]["upstreamVersionScope"] = (
                "与inputRoles逐项相同的resourceId/revision不重复，差异版本仍列于upstreamVersions。"
            )
    algorithm = payload.get("allowedAlgorithm", {})
    manifest = algorithm.get("manifest")
    if isinstance(manifest, dict):
        # The action, ports and parameters are already frozen by the workflow.
        # The reviewer proposes member dispositions; it cannot rewire this graph.
        payload["batchEvidenceProjection"]["algorithmContractSha256"] = hashlib.sha256(
            dumps(manifest).encode()
        ).hexdigest()
        algorithm["manifest"] = {
            key: value
            for key, value in manifest.items()
            if key in {"identifier", "name", "version", "parameters"}
        }
        payload["batchEvidenceProjection"]["algorithmScope"] = (
            "已冻结的动作、算法版本、校验和及参数约束；完整端口契约保留在原审计，"
            "本批只能提出成员处置，不能替换算法、端口绑定或计算参数。"
        )
    return payload


def _execution_knowledge(payload, level, original):
    """Keep exact rule predicates; leave display metadata in the source audit."""
    knowledge = payload.get("knowledge", [])
    if level < 3 or not any(entry.get("trialBinding") for entry in knowledge):
        return payload
    retained, deferred, omitted = [], [], set()
    fields = {
        "id",
        "revision",
        "title",
        "status",
        "statement",
        "conditions",
        "exceptions",
        "ruleConfig",
        "trialBinding",
        "content",
        "body",
        "description",
    }
    action = payload.get("allowedAction")
    for entry in knowledge:
        binding = entry.get("trialBinding", {})
        # Prospect grading rules are not run by the knowledge-check operator.
        # They remain frozen for its later prospect stage, rather than being
        # silently treated as read or cited by this calculation decision.
        if action == "geology-multi-check" and str(
            binding.get("ruleId", "")
        ).startswith("P-"):
            deferred.append(
                {
                    "id": entry["id"],
                    "revision": entry["revision"],
                    "ruleId": binding["ruleId"],
                    "reason": "later_prospect_stage",
                }
            )
            continue
        config = entry.get("ruleConfig")
        if not binding or not (
            isinstance(config, dict) and isinstance(config.get("rule"), dict)
        ):
            # Unstructured knowledge still needs its actual explanatory text.
            keep = fields | {"subject", "predicate", "object", "explanation"}
        else:
            keep = fields
        omitted.update(set(entry) - keep)
        view = {key: value for key, value in entry.items() if key in keep}
        if "explanation" in entry and "explanation" not in keep:
            view["explanation"] = ""
        retained.append(view)
    payload["knowledge"] = retained
    identities = {str(entry["id"]) for entry in retained}
    if "availableEvidence" in payload:
        payload["availableEvidence"] = [
            ref
            for ref in payload["availableEvidence"]
            if ref["kind"] != "knowledge" or str(ref["id"]) in identities
        ]
    payload["knowledgeProjection"] = {
        "view": "execution_conditions_exceptions_and_exact_rule_config",
        "sourceSha256": hashlib.sha256(
            dumps(original.get("knowledge", [])).encode()
        ).hexdigest(),
        "sourceCount": len(knowledge),
        "shownCount": len(retained),
        "omittedFields": sorted(omitted),
        "deferred": deferred,
        "note": (
            "条件、例外、结构化规则和版本按原值保留；展示性元数据、"
            "来源摘录与结构化规则之外的解释留在完整审计，未展示内容不能作为额外依据。"
            "deferred条目尚未审阅，只能引用availableEvidence中的实际展示知识。"
        ),
    }
    algorithm = payload.get("allowedAlgorithm", {})
    manifest = algorithm.get("manifest")
    if isinstance(manifest, dict):
        for key in (
            "author",
            "runtime",
            "agent",
            "qualityReport",
            "schemaVersion",
            "timeoutSeconds",
            "deterministic",
        ):
            manifest.pop(key, None)
        for name in ("inputs", "outputs"):
            for item in manifest.get(name, []):
                item.pop("label", None)
                item.pop("file", None)
        # Required types, geometry/band constraints, parameter bounds, output
        # keys, algorithm identity and immutable checksum remain available.
    return payload


def _focus_batch(payload, level):
    """Do not spend the reviewer's window on repeated execution/audit headers."""
    if (
        level < 3
        or payload.get("allowedAction") != "geology-multi-apply"
        or not payload.get("modelBatch", {}).get("completeMembers")
    ):
        return payload
    for role in payload.get("inputRoles", []):
        role.pop("revision", None)
        metadata = role.get("metadata", {})
        role["metadata"] = {
            key: value
            for key, value in metadata.items()
            if key in {"fields", "warnings", "qualityCheck"}
        }
        if role.get("role") == "rules":
            for key in ("description", "readingScope", "sourceRowCount", "sourceScope"):
                role.pop(key, None)
        elif role.get("description", "").startswith("MH-workflow任务资料，原文件："):
            role.pop("description", None)
    previous = payload.get("previousDecisions", [])
    payload["previousDecisions"] = [
        {
            key: value
            for key, value in item.items()
            if key in {"judgement", "nextAction"}
        }
        for item in previous[-1:]
    ]
    state = payload.get("executionState", {})
    payload["executionState"] = {
        "currentStage": state.get("currentStage"),
        "latestStatisticsOutputIds": state.get("currentRun", {}).get(
            "latestStatisticsOutputIds", []
        ),
    }
    # Cryptographic proofs belong to the complete source/request audit. The
    # model needs object identities, versions and measured values to judge them.
    audit_keys = {
        "checksum",
        "snapshot_hash",
        "scopeSha256",
        "sourceSha256",
        "algorithmContractSha256",
    }

    def audit_headers(value):
        if isinstance(value, dict):
            for key in list(value):
                if key in audit_keys:
                    value.pop(key)
                elif key not in {
                    "conditions",
                    "exceptions",
                    "ruleConfig",
                    "measurements_json",
                    "measurements",
                    "measurementCommon",
                }:
                    audit_headers(value[key])
        elif isinstance(value, list):
            for item in value:
                audit_headers(item)

    for key in (
        "actualResults",
        "allowedAlgorithm",
        "modelBatch",
        "batchEvidenceProjection",
        "knowledgeProjection",
        "batchKnowledgeScope",
    ):
        audit_headers(payload.get(key))
    payload["batchEvidenceProjection"]["auditScope"] = (
        "完整来源指纹、契约、版本与请求保留在原始阶段审计；平台按原值校验。"
        "本视图省略纯审计指纹及重复执行头，不能据此改变绑定或扩大建议范围。"
    )
    if "upstreamVersionScope" in payload["batchEvidenceProjection"]:
        payload["batchEvidenceProjection"]["upstreamVersionScope"] = (
            "相同输入版本由平台冻结校验并保存在原始阶段审计；差异版本仍在upstreamVersions展开。"
        )
    payload["modelBatch"].pop("instruction", None)
    return payload


def _bounded_evidence(payload, level):
    """Project tables before sending; complete inputs remain in the stage audit."""
    projections = []
    complete_facts = execution_fact_paths(payload)
    execution_scope = execution_evidence_scope(payload)

    def bounded(items, limit, path, columns=None):
        if len(items) <= limit:
            return items
        ranges, representatives = {}, []
        for index, row in enumerate(items):
            cells = (
                row
                if isinstance(row, dict)
                else (
                    dict(zip(columns, row))
                    if columns and isinstance(row, list) and len(columns) == len(row)
                    else {}
                )
            )
            for name, value in cells.items():
                number = _number(value)
                if number is None:
                    continue
                measured = ranges.setdefault(name, [number, number, index, index])
                if number < measured[0]:
                    measured[0], measured[2] = number, index
                if number > measured[1]:
                    measured[1], measured[3] = number, index
            if cells.get("status") in {"review", "exception", "needs_review"}:
                representatives.append(index)
        candidates = [0, len(items) - 1, *representatives[:limit]]
        candidates.extend(index for item in ranges.values() for index in item[2:])
        candidates.extend(
            round(i * (len(items) - 1) / (limit - 1)) for i in range(limit)
        )
        selected = sorted(dict.fromkeys(candidates))
        if len(selected) > limit:
            # Preserve the priority order before restoring original table order.
            selected = sorted(list(dict.fromkeys(candidates))[:limit])
        summary = {
            "path": path,
            "inputCount": len(items),
            "shownCount": len(selected),
            "omittedCount": len(items) - len(selected),
            "shownIndices": selected,
            "sourceSha256": hashlib.sha256(dumps(items).encode()).hexdigest(),
            "selection": "boundary_exception_extrema_then_even_spacing",
            "coverage": "shown_items_only",
        }
        if ranges:
            summary["completeInputNumericRanges"] = {
                key: item[:2] for key, item in ranges.items()
            }
        if path.endswith(".groups"):
            summary["completeInputObjectCount"] = sum(
                item.get("count", 0) for item in items if isinstance(item, dict)
            )
        projections.append(summary)
        return [items[index] for index in selected]

    def walk(value, path=""):
        if isinstance(value, dict):
            for name, item in list(value.items()):
                child = f"{path}.{name}" if path else name
                complete_batch = payload.get("modelBatch", {}).get("completeMembers")
                batch_groups = (
                    complete_batch
                    and child.startswith("actualResults[")
                    and name == "groups"
                )
                batch_totals = (
                    complete_batch
                    and child.startswith("actualResults[")
                    and value.get("key") in {"statistics", "alteration_quality"}
                    and name == "rows"
                )
                if (
                    name in BOUNDED_LISTS
                    and isinstance(item, list)
                    and not batch_groups
                    and not batch_totals
                    and child not in complete_facts
                ):
                    limit = (
                        GROUP_LIMITS[level] if name == "groups" else ROW_LIMITS[level]
                    )
                    original_count = len(item)
                    item = bounded(item, limit, child, value.get("columns"))
                    value[name] = item
                    if len(item) != original_count and name in {"rows", "groups"}:
                        value.setdefault("sourceScope", value.get("scope"))
                        value["scope"] = "bounded_model_sample"
                # Rule predicates and knowledge exceptions must remain exact.
                if name not in {"ruleConfig", "conditions", "exceptions"} and not (
                    execution_scope and name in QUALITY_KEYS
                ):
                    walk(item, child)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")

    walk(payload)
    if projections:
        payload["evidenceProjection"] = projections
        payload["evidenceProjectionNote"] = REFERENCE_NOTE
    return payload


def project_payload(original, level):
    if not level:
        return _bounded_evidence(copy.deepcopy(original), level)
    payload = _expand_knowledge(original)
    if "colorCandidates" in payload:
        candidates = payload["colorCandidates"]
        if level >= 2:
            candidates = [item for item in candidates if item["relevance"] == 0]
        if level >= 3:
            seen, selected = set(), []
            for item in candidates:
                if item["value"] not in seen:
                    selected.append(item)
                    seen.add(item["value"])
            candidates = selected
        if level >= 4:
            candidates = []
        payload["colorCandidates"] = candidates
        return _deduplicate(_bounded_evidence(payload, level))
    payload = project_execution_evidence(payload, level)
    payload = _execution_batch_evidence(payload, level)
    payload = _execution_knowledge(payload, level, original)
    bindings = {}
    for role in payload.get("inputRoles", []):
        if role.get("role") == "rules":
            for row in role.get("rows", []):
                if row.get("knowledge_id"):
                    bindings[row.get("rule_id")] = {
                        "id": row["knowledge_id"],
                        "revision": row.get("knowledge_revision"),
                    }
    for entry in payload.get("knowledge", []):
        bound = entry.get("trialBinding", {})
        if bound.get("ruleId"):
            bindings[bound["ruleId"]] = {
                "id": entry["id"],
                "revision": entry["revision"],
            }
        for key in ("statement", "explanation", "content", "body", "description"):
            text = entry.get(key)
            if isinstance(text, str) and len(text) > 160:
                passages = re.findall(r"[^。；\n]+[。；\n]?", text)
                entry[key] = "".join(dict.fromkeys(passages))
    for result in payload.get("actualResults", []):
        for group in result.get("groups", []):
            if group.get("rule_id") in bindings:
                group["requiredKnowledgeRefs"] = [bindings[group["rule_id"]]]
    if level >= 2:
        rule_texts = {
            entry.get("trialBinding", {}).get("ruleId"): dumps(
                entry.get("ruleConfig", {})
            )
            for entry in payload.get("knowledge", [])
        }
        for result in payload.get("actualResults", []):
            for group in result.get("groups", []):
                rule_text = rule_texts.get(group.get("rule_id"), "")
                if payload.get("modelBatch", {}).get("completeMembers"):
                    continue
                group["samples"] = group.get("samples", [])[:1] if level < 4 else []
                for sample in group["samples"]:
                    if "measurements_json" in sample:
                        measurements = json.loads(sample["measurements_json"] or "{}")
                        sample["measurements_json"] = dumps(
                            {
                                key: value
                                for key, value in measurements.items()
                                if key in rule_text
                            }
                        )
                    if "reason" in sample:
                        sample["reason"] = _summary(sample["reason"], 240)
    if level >= 3:
        relevant = {
            group.get("rule_id")
            for result in payload.get("actualResults", [])
            for group in result.get("groups", [])
        }
        for entry in payload.get("knowledge", []):
            active = (
                not relevant or entry.get("trialBinding", {}).get("ruleId") in relevant
            )
            for key in ("statement", "explanation", "content", "body", "description"):
                if key in entry:
                    entry[key] = _summary(
                        entry[key], (800 if level == 3 else 256) if active else 120
                    )
        payload["previousDecisions"] = [
            _history(item) for item in payload.get("previousDecisions", [])
        ]
        previous = payload.get("previousAnalysis")
        if isinstance(previous, dict):
            payload["previousAnalysis"] = _history(previous)
            if "oldDecision" in previous:
                payload["previousAnalysis"]["oldDecision"] = _history(
                    previous["oldDecision"]
                )
    payload = _focus_batch(payload, level)
    return _deduplicate(_bounded_evidence(payload, level))


def projected_messages(messages, payload, level):
    projected = [dict(item) for item in messages[:2]]
    value = project_payload(payload, level)
    if level or "evidenceProjection" in value:
        projected[0]["content"] += (
            "预算投影使用contextDefinitions及$ref引用，先解引用再判断；"
            "节选不构成额外知识依据，缺失依据须request_review。"
        )
        projected[1]["content"] = dumps(value)
    return projected


def visible_payload(original, level):
    projected = project_payload(original, level)
    definitions = projected.get("contextDefinitions", {})

    def expand(value):
        if isinstance(value, dict):
            if set(value) == {"$ref"}:
                return expand(definitions[value["$ref"]])
            return {
                key: expand(item)
                for key, item in value.items()
                if key != "contextDefinitions"
            }
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value

    return expand(projected)


def assert_visible_edits(edits, payload):
    """A source-valid identifier alone does not prove the model saw its evidence."""
    groups, rows = {}, []
    for result in payload.get("actualResults", []):
        if result.get("key") != "issues":
            continue
        rows.extend(result.get("rows", []))
        for group in result.get("groups", []):
            groups[group["group_id"]] = group
            rows.extend(group.get("samples", []))
    ids = {row.get("issue_id") for row in rows if isinstance(row, dict)}
    for edit in edits:
        if not isinstance(edit, dict):
            continue
        if "group_id" in edit:
            group = groups.get(edit["group_id"])
            if group is None:
                raise ValueError("建议分组未在本次模型证据中展示")
            if (
                edit.get("disposition") != "review"
                and len(group.get("samples", [])) != group["count"]
            ):
                raise ValueError(
                    "代表样本不足以支持整组建议，请逐对象核对完整本批成员或请求复核"
                )
        elif "issue_id" in edit:
            if edit["issue_id"] not in ids:
                raise ValueError("建议对象未在本次实际检查的模型证据中展示")
        elif "feature_id" in edit and not any(
            isinstance(row, dict)
            and all(
                str(row.get(key, "")) == str(edit.get(key, ""))
                for key in (
                    "feature_id",
                    "field",
                    "old_value",
                    "new_value",
                    "evidence_id",
                    "rule_id",
                )
            )
            for row in rows
        ):
            raise ValueError("属性修改对象及依据未在本次实际检查的模型证据中完整展示")


def budget_review(stage, payload, error):
    stage["modelRequestPayload"] = copy.deepcopy(payload)
    stage["contextBudgetReview"] = {"reason": str(error), "maxLevel": MAX_LEVEL}
    raise BudgetReviewRequired(
        "必要证据在分级压缩后仍超出模型输入预算，未提交本阶段计算。"
        "请调整模型窗口后继续分析，或缩小资料范围重新发起；完整证据和请求审计已保留。"
    )
