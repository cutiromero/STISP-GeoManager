"""Bounded representative readings, with complete file identity and measured totals."""

import csv
import hashlib
import json
import math
from collections import Counter

from apps.compute.packages import ComputeError


def table_rows(path, key):
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ComputeError("综合检查结果表超过64 MiB，请缩小本次检查范围")
    groups, rows, count, counts = {}, [], 0, Counter()
    all_issues = []
    evidence_groups, combinations = {}, {}
    seen_zones = set()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(reader.fieldnames) > 80:
            raise ComputeError("综合检查结果表字段无效")
        for row in reader:
            count += 1
            if key != "issues" and count > 100000:
                raise ComputeError("综合检查结果超过十万项，请缩小检查范围")
            if any(value is None or len(value) > 160000 for value in row.values()):
                raise ComputeError("综合检查结果包含异常单元格")
            group = row.get("rule_id", "statistics")
            counts[group] += 1
            if key == "issues":
                all_issues.append(row)
            elif key == "evidence":
                zone = (row.get("phase"), row.get("zone_id"))
                if zone in seen_zones:
                    raise ComputeError("远景区证据包含重复的同分期对象，已停止面积汇总")
                _aggregate_evidence(row, evidence_groups, combinations)
                seen_zones.add(zone)
                representatives = groups.setdefault(
                    (row["phase"], row.get("grade", "")), []
                )
                representatives.append(row)
                representatives.sort(
                    key=lambda item: float(item["area_km2"]), reverse=True
                )
                del representatives[2:]
            elif (
                key
                in {"statistics", "changes", "alteration_summary", "alteration_quality"}
                or len(rows) < 40
            ):
                rows.append(row)
    current_evidence = key == "evidence" and "schema_version" in reader.fieldnames
    if key == "evidence":
        rows = [row for representatives in groups.values() for row in representatives]
    if key == "issues":
        rows = all_issues
    result = {
        "columns": reader.fieldnames,
        "rows": rows,
        "rowCount": count,
        "scope": "all" if count == len(rows) else "representative_sample",
        "samplingNote": (
            (
                "全部修正后远景区参与汇总；展示面积最大的两个代表，完整对象依据可下载"
                if current_evidence
                else "全部远景区均参与分期、等级及证据组合汇总；每个分期和等级展示面积最大的两个代表，完整对象证据可下载"
            )
            if key == "evidence"
            else "完整检查对象参与分组建议；模型接收分组数量、实测分布及代表样本，未获批对象保持原样"
        ),
        "countsByRule": dict(counts),
    }
    if key == "evidence":
        result["aggregate"] = {
            "scope": "all_rows",
            "rowCount": count,
            ("byPhase" if current_evidence else "byPhaseAndGrade"): _finish_groups(
                evidence_groups
            ),
            "schemaVersion": 2 if current_evidence else 1,
            "evidenceCombinations": _finish_groups(combinations),
            "countUnit": "zone",
            "aggregationNote": "以(phase,zone_id)唯一对象计数；汇总表是同一完整证据表的不同分组，面积不相加",
            "interpretation": "实测比例给出各区取值范围；邻近矿物、断裂与交汇作为背景，条件是否满足以实际表达式与实测为准",
        }
    return result


def _evidence_basis(row):
    try:
        basis = json.loads(row["evidence_json"])
        current = row.get("schema_version") == "2"
        if "schema_version" in row and not current:
            raise ValueError("unsupported evidence version")
        if current and (
            basis.get("schema_version") != 2
            or row["phase"] != "after"
            or "grade" in row
        ):
            raise ValueError("invalid corrected-only protocol")
        measured, context = (
            basis["conditions" if current else "grade_conditions"],
            basis["context"],
        )
        area = float(row["area_km2"])
        if (
            not isinstance(measured, dict)
            or not isinstance(context, dict)
            or not math.isfinite(area)
            or area < 0
            or not row["phase"]
            or (not current and not row["grade"])
            or not row["zone_id"]
            or basis["phase"] != row["phase"]
            or not isinstance(context["minerals"], list)
            or not all(isinstance(value, str) for value in context["minerals"])
            or not isinstance(measured["rule_expression"], str)
            or not isinstance(basis["knowledge"], list)
        ):
            raise ValueError("invalid evidence")
        for key in ("faults", "intersections"):
            if not isinstance(context[key], list) or not all(
                isinstance(item, dict) for item in context[key]
            ):
                raise ValueError("invalid associations")
        for key in (
            "structure_supported_fraction",
            "alteration_supported_fraction",
            "favourable_fraction",
            "min_weighted_type_count",
        ):
            if not math.isfinite(float(measured[key])):
                raise ValueError("invalid measurement")
    except (ValueError, TypeError, KeyError) as exc:
        raise ComputeError("远景区证据缺少有效分期、面积、实测条件或知识引用") from exc
    return basis, measured, context, area


def _aggregate_evidence(row, groups, combinations):
    basis, measured, context, area = _evidence_basis(row)
    phase, grade = row["phase"], row.get("grade", "")
    dimensions = (
        {"phase": phase}
        if basis.get("schema_version") == 2
        else {"phase": phase, "grade": grade}
    )
    minerals = tuple(sorted(set(context["minerals"])))
    expression = measured["rule_expression"]
    for table, key, dimensions in (
        (groups, (phase, grade), dimensions),
        (
            combinations,
            (phase, grade, expression, minerals),
            {
                **dimensions,
                "ruleExpression": expression,
                "minerals": list(minerals),
            },
        ),
    ):
        group = table.setdefault(
            key,
            {
                **dimensions,
                "zoneCount": 0,
                "areas": [],
                "knowledge": {},
                "measurementRanges": {},
            },
        )
        group["zoneCount"] += 1
        group["areas"].append(area)
        for name in (
            "structure_supported_fraction",
            "alteration_supported_fraction",
            "favourable_fraction",
            "min_weighted_type_count",
        ):
            value = float(measured[name])
            values = group["measurementRanges"].setdefault(
                name, {"min": value, "max": value}
            )
            values["min"], values["max"] = (
                min(values["min"], value),
                max(values["max"], value),
            )
        for citation in basis["knowledge"]:
            if not isinstance(citation, dict):
                raise ComputeError("远景区知识引用格式无效")
            group["knowledge"][json.dumps(citation, sort_keys=True)] = citation


def _finish_groups(groups):
    return [
        {
            **{
                key: value
                for key, value in group.items()
                if key not in {"areas", "knowledge"}
            },
            "areaKm2": math.fsum(group["areas"]),
            "knowledge": list(group["knowledge"].values()),
        }
        for _, group in sorted(groups.items())
    ]


def model_results(results, *, stage_name):
    """Geometry is available to the map; narrative decisions use actual measurements."""
    values, shared_metadata = [], {}
    for item in results:
        value = {
            **item,
            "rows": [
                {key: cell for key, cell in row.items() if key != "geometry_json"}
                for row in item.get("rows", [])
            ],
        }
        if item["key"] == "issues" and stage_name == "apply":
            from .geology_issue_groups import group_summaries

            value.update(
                rows=[],
                groups=group_summaries(
                    [
                        row
                        for row in item.get("rows", [])
                        if not row.get("feature_id", "").startswith("AG-")
                    ]
                ),
                scope="all_groups",
            )
        if item["key"] == "changes":
            grouped = {}
            for row in item.get("rows", []):
                key = (
                    row.get("element", ""),
                    row.get("rule_id", ""),
                    row.get("action", ""),
                )
                group = grouped.setdefault(
                    key,
                    {
                        "element": key[0],
                        "rule_id": key[1],
                        "action": key[2],
                        "count": 0,
                        "actualChanged": 0,
                    },
                )
                group["count"] += 1
                group["actualChanged"] += str(
                    row.get("actual_changed", "")
                ).lower() in {"true", "1"}
            value.update(rows=list(grouped.values()), scope="all_groups")
            value.pop("columns", None)
        if item["key"] == "issues" and stage_name != "apply":
            value.update(
                rows=[],
                scope="reference_only",
                samplingNote="历史问题明细保存在完整输出；本阶段依据完整规则统计及实际获批修改继续复核，不重复发送历史候选对象",
            )
            value.pop("columns", None)
        elif item["key"] == "evidence":
            value["rows"] = [_model_evidence_row(row) for row in item.get("rows", [])]
            if "aggregate" in item:
                value["aggregate"], value["rows"] = _model_evidence(
                    item["aggregate"], value["rows"]
                )
        if "metadata" in item:
            value["metadata"] = _model_metadata(
                item, shared_metadata, columns=value.get("columns")
            )
        if item["key"] == "statistics":
            value.update(_column_rows(value["rows"], value.get("columns")))
        if item["key"] == "alteration_summary":
            grouped = {}
            for row in value["rows"]:
                keys = (
                    "rule_id",
                    "rule_version",
                    "knowledge_id",
                    "knowledge_revision",
                    "mineral",
                    "rock_group",
                    "boundary",
                    "suggested_action",
                    "status",
                )
                identity = tuple(row[key] for key in keys)
                group = grouped.setdefault(
                    identity,
                    {
                        **{key: row[key] for key in keys},
                        "group_count": 0,
                        "pixel_count": 0,
                        "area_m2": 0.0,
                        "component_count": 0,
                        "unit_codes": set(),
                    },
                )
                group["group_count"] += 1
                group["pixel_count"] += int(row["pixel_count"])
                group["area_m2"] += float(row["area_m2"])
                group["component_count"] += int(row["component_count"])
                group["unit_codes"].add(row["unit_code"])
            value["rows"] = [
                {
                    **group,
                    "unit_count": len(group["unit_codes"]),
                    "unit_codes": sorted(group["unit_codes"])[:20],
                }
                for group in grouped.values()
            ]
            value.update(_column_rows(value["rows"]))
            value["scope"] = "all_raster_groups_aggregated_by_rock_group"
        if item["key"] == "group_index":
            value.update(rows=[], scope="reference_only")
        values.append(value)
    return values


def public_plan(plan):
    """Keep display facts, not internal full-resolution checks or model requests."""

    def public_stage(stage):
        value = {
            key: item
            for key, item in stage.items()
            if key
            not in {
                "edits",
                "proposedEdits",
                "modelRequestPayload",
                "modelRequestInstruction",
                "modelAttempts",
                "modelBudgetHistory",
                "modelBatches",
            }
        }
        if "results" in value:
            value["results"] = [
                model_results([item], stage_name="apply")[0]
                if isinstance(item, dict) and item.get("key") == "issues"
                else item
                for item in value["results"]
            ]
        return value

    public = {
        **{
            key: value
            for key, value in plan.items()
            if key
            not in {
                "modificationReview",
                "previousAnalysis",
                "retainedReviewHistory",
                "reportInterpretationHistory",
            }
        },
        "stages": [public_stage(stage) for stage in plan.get("stages", [])],
    }
    if isinstance(public.get("finalStage"), dict):
        public["finalStage"] = public_stage(public["finalStage"])
    return public


def _column_rows(rows, columns=None):
    columns = list(columns or (rows[0] if rows else []))
    if any(set(row) != set(columns) for row in rows):
        raise ComputeError("综合检查表格列与明细不一致，已停止模型投影")
    return {
        "columns": columns,
        "rows": [[row[name] for name in columns] for row in rows],
        "rowFormat": "columns",
    }


def _model_metadata(item, shared, *, columns=None):
    """Send identical task facts once, retaining an exact source reference elsewhere."""
    metadata = {**item["metadata"]}
    if "fields" in metadata:
        fields = metadata["fields"]
        identity = ("fields", json.dumps(fields, ensure_ascii=False))
        if columns is not None and columns == fields:
            del metadata["fields"]
            metadata["fieldsRef"] = {
                "outputId": item.get("outputId"),
                "path": "columns",
            }
            shared.setdefault(identity, metadata["fieldsRef"])
        elif identity in shared:
            del metadata["fields"]
            metadata["fieldsRef"] = shared[identity]
        else:
            shared[identity] = {
                "outputId": item.get("outputId"),
                "path": "metadata.fields",
            }
    quality = metadata.get("qualityCheck", {})
    facts = metadata.get("knowledgeFacts", {})
    duplicate_facts = facts and facts == {"geologyMulti": quality.get("metrics")}
    if duplicate_facts:
        del metadata["knowledgeFacts"]
    quality_source = None
    for key in ("qualityCheck", "knowledgeFacts"):
        if key not in metadata:
            continue
        signature = json.dumps(metadata[key], sort_keys=True, ensure_ascii=False)
        identity = (item.get("taskId"), key, signature)
        if identity in shared:
            del metadata[key]
            metadata[f"{key}Ref"] = shared[identity]
        else:
            shared[identity] = {
                "outputId": item.get("outputId"),
                "path": f"metadata.{key}",
            }
        if key == "qualityCheck":
            quality_source = shared[identity]
    if duplicate_facts:
        metadata["knowledgeFactsRef"] = {
            "outputId": quality_source.get("outputId"),
            "path": "metadata.qualityCheck.metrics",
            "scope": "geologyMulti",
        }
    return metadata


def _model_evidence_row(row):
    basis, measured, context, area = _evidence_basis(row)
    return {
        "phase": row["phase"],
        "zoneId": row["zone_id"],
        **({"grade": row["grade"]} if "grade" in row else {"schemaVersion": 2}),
        "areaKm2": area,
        "explanation": row.get("explanation", ""),
        (
            "conditions" if basis.get("schema_version") == 2 else "gradeConditions"
        ): measured,
        "knowledge": basis["knowledge"],
        "minerals": context["minerals"],
        "faultAssociations": len(context["faults"]),
        "intersectionAssociations": len(context["intersections"]),
        "inferredIntersectionAssociations": sum(
            bool(item.get("inferred")) for item in context["intersections"]
        ),
        "lithologyAreasM2": context.get("lithology_areas_m2", {}),
        "contextScope": "实测条件、关联数量及岩性面积；完整关联对象和条件保存在原输出",
    }


def _model_evidence(aggregate, rows):
    """Factor repeated evidence values; every group, range and citation is retained."""
    definitions, identities = {}, {}

    def project(item):
        projected = {}
        for key, value in item.items():
            if key not in {
                "knowledge",
                "measurementRanges",
                "ruleExpression",
                "gradeConditions",
                "conditions",
                "minerals",
            }:
                projected[key] = value
                continue
            signature = (key, json.dumps(value, sort_keys=True, ensure_ascii=False))
            if signature not in identities:
                reference = f"{key}{len(identities) + 1}"
                definitions[reference] = value
                identities[signature] = reference
            projected[f"{key}Ref"] = identities[signature]
        return projected

    result = {**aggregate}
    for key in ("byPhase", "byPhaseAndGrade", "evidenceCombinations"):
        if key in aggregate:
            result[key] = [project(item) for item in aggregate[key]]
    result["evidenceCombinations"] = _column_rows(result["evidenceCombinations"])
    projected_rows = [project(row) for row in rows]
    result["definitions"] = definitions
    result["referenceNote"] = (
        "以Ref结尾的字段引用本aggregate.definitions中的完整原值；所有分组、数量、面积、实测范围及知识引用均保留"
    )
    return result, projected_rows


def model_knowledge(knowledge):
    """Use exact field references for repeated passages, preserving the full evidence."""
    seen = {}

    def project(value, path):
        if isinstance(value, (dict, list, str)):
            signature = json.dumps(value, sort_keys=True, ensure_ascii=False)
            if len(signature.encode()) >= 80:
                if signature in seen:
                    return {"sameAs": seen[signature]}
                seen[signature] = path
        if isinstance(value, dict):
            return {key: project(item, f"{path}.{key}") for key, item in value.items()}
        if isinstance(value, list):
            return [
                project(item, f"{path}[{index}]") for index, item in enumerate(value)
            ]
        return value

    return [
        project(item, f"knowledge[{index}]") for index, item in enumerate(knowledge)
    ]


def model_review(workflow):
    """Keep approval semantics and original-output bindings; map keeps full geometry."""
    review = workflow.plan.get("modificationReview")
    if review is None:
        return None
    suggestions, groups = [], {}
    approved = set(review.get("approvedSuggestionIds", []))
    actions = {
        group_id: action
        for stage in workflow.plan.get("stages", [])
        for group_id, action in stage.get("modificationsApproval", {})
        .get("alterationActions", {})
        .items()
    }
    for item in review["suggestions"]:
        if item["id"] in approved and item.get("featureId") in actions:
            item = {**item, "action": actions[item["featureId"]]}
        raster = str(item.get("featureId", "")).startswith("AG-")
        observations = item.get("observations", {})
        key = (
            (
                item.get("element"),
                item.get("ruleId"),
                item.get("action"),
                observations.get("mineral"),
                observations.get("rock_group"),
                observations.get("boundary"),
            )
            if raster
            else item.get("groupId")
            or (
                item.get("element"),
                item.get("ruleId"),
                item.get("action"),
                item.get("suggestedState"),
            )
        )
        group = groups.setdefault(
            key,
            {
                "element": item.get("element"),
                "ruleId": item.get("ruleId"),
                "action": item.get("action"),
                "count": 0,
                "approvedCount": 0,
            },
        )
        group["count"] += 1
        group["approvedCount"] += item["id"] in approved
        if raster:
            group["pixelCount"] = group.get("pixelCount", 0) + observations.get(
                "pixel_count", 0
            )
            group["areaM2"] = group.get("areaM2", 0) + item.get("areaM2", 0)
            group.update(
                mineral=observations.get("mineral"),
                rockGroup=observations.get("rock_group"),
                boundary=observations.get("boundary"),
            )
            continue
        if group["count"] > 2:
            continue
        suggestions.append(
            {
                **{
                    key: item.get(key)
                    for key in (
                        "id",
                        "element",
                        "featureId",
                        "currentState",
                        "suggestedState",
                        "reason",
                        "action",
                        "status",
                        "areaM2",
                        "lengthM",
                        "observations",
                    )
                },
                "ruleRefs": [
                    {
                        key: ref[key]
                        for key in ("id", "version", "knowledgeId", "revision")
                    }
                    for ref in item["ruleRefs"]
                ],
            }
        )
    check = next(stage for stage in workflow.plan["stages"] if stage["name"] == "check")
    return {
        "proposalHash": review["proposalHash"],
        "approvedSuggestionIds": review.get("approvedSuggestionIds", [])[:3],
        "unapprovedSuggestionIds": review.get("unapprovedSuggestionIds", [])[:3],
        "approvedCount": len(approved),
        "suggestionCount": len(review["suggestions"]),
        "groups": list(groups.values()),
        "scope": "all_groups_with_representative_ids",
        "approvalScopeDigest": hashlib.sha256(
            json.dumps(sorted(approved)).encode()
        ).hexdigest(),
        "suggestions": _column_rows(suggestions),
        "sourceOutputs": [
            {key: item[key] for key in ("outputId", "taskId", "key", "checksum")}
            for item in check.get("results", [])
            if item["key"] == "issues"
        ],
        "geometryScope": "完整预览几何保存在原批准方案和地图，模型仅接收处置语义、规则绑定和实际输出引用",
    }


def approval_statistics(review):
    if not review:
        return review
    additive = {"count", "approvedCount", "areaM2", "pixelCount"}
    grouped = {}
    for row in review.get("groups", []):
        dimensions = {key: value for key, value in row.items() if key not in additive}
        signature = json.dumps(dimensions, sort_keys=True, ensure_ascii=False)
        group = grouped.setdefault(signature, dict(dimensions))
        for key in additive & row.keys():
            group[key] = group.get(key, 0) + row[key]
    return {
        **{
            key: value
            for key, value in review.items()
            if key
            not in {
                "suggestions",
                "approvedSuggestionIds",
                "unapprovedSuggestionIds",
                "groups",
            }
        },
        "groups": list(grouped.values()),
        "scope": "complete_rule_action_counts",
        "detailScope": "完整批准数量、分组面积与像元数；逐对象决定由原方案和approvalScopeDigest绑定，本次不重新审阅或扩大批准",
    }


def edit_task(workflow, results):
    if not results:
        return None
    check = next(item for item in workflow.plan["stages"] if item["name"] == "check")
    issues = [
        item
        for item in results
        if item["key"] == "issues" and item["taskId"] == check.get("taskId")
    ]
    return {
        "issuesOutputIds": [item["outputId"] for item in issues],
        "requiredFields": ["group_id", "disposition", "excluded_issue_ids", "reason"],
        "changesInputState": "requires_model_proposal",
        "groupDisposition": ["suggested", "review"],
        "overlapPolicy": "同一对象命中多组时，按原检查清单顺序采用首条已选择的建议；每个对象仅执行一次",
        "unselectedPolicy": "retain_original",
        "issueRuleKnowledge": [
            {
                "id": item["id"],
                "revision": item["revision"],
                "ruleId": item["ruleId"],
                "ruleVersion": item["ruleVersion"],
            }
            for item in workflow.plan["trialRuleBindings"]
        ],
    }
