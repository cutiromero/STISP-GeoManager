from __future__ import annotations

from collections import Counter
import copy
import json
import math
import re

from shapely.geometry import mapping, shape

PAGE_LIMIT = 50
SUMMARY_KEYS = (
    "phase",
    "stageIndex",
    "deletedResources",
    "multiElementMap",
    "inputs",
    "inputNames",
    "missingRoles",
    "upstreamVersions",
    "outcome",
    "fieldMappingReview",
    "reusedConfiguration",
)
STAGE_KEYS = ("name", "identifier", "status", "taskId", "outputs", "outcome")


def page_options(query, view):
    from .views import ApiProblem

    part = query.get("part", "changes" if view == "compare" else "suggestions")
    if part not in ({"changes"} if view == "compare" else {"suggestions", "steps"}):
        raise ApiProblem("工作流分页内容无效")
    try:
        offset = int(query.get("offset", 0))
        limit = int(query.get("limit", 0 if view == "compare" else PAGE_LIMIT))
    except (ValueError, TypeError) as exc:
        raise ApiProblem("工作流分页参数无效") from exc
    if offset < 0 or not 0 <= limit <= PAGE_LIMIT:
        raise ApiProblem("工作流分页参数超出范围")
    return part, offset, limit


def bounded(value, depth=0):
    if depth > 6:
        return None
    if isinstance(value, str):
        return value[:2000]
    if isinstance(value, list):
        return [bounded(item, depth + 1) for item in value[:12]]
    if isinstance(value, dict):
        return {
            key: bounded(item, depth + 1)
            for key, item in list(value.items())[:40]
            if key
            not in {
                "modelRequestPayload",
                "modelRequestInstruction",
                "modelAttempts",
                "modelBudgetHistory",
                "modelBatches",
                "edits",
                "proposedEdits",
                "preview",
            }
        }
    return value


def display_preview(preview):
    if not preview:
        return {"type": "Polygon", "coordinates": []}
    geometry = mapping(shape(preview).simplify(0.0001, preserve_topology=True))

    def quantize(value):
        if isinstance(value, (list, tuple)):
            return [quantize(item) for item in value]
        return round(value, 5) if isinstance(value, float) else value

    return {**geometry, "coordinates": quantize(geometry["coordinates"])}


def _identity(item, suggestion=False):
    keys = (
        ("featureId", "ruleId", "action")
        if suggestion
        else ("feature_id", "rule_id", "action")
    )
    return tuple(str(item.get(key, "")) for key in keys)


def review_index(suggestions):
    groups = {}
    for item in suggestions:
        held = item.get("status") != "suggested" or item.get("action") in {
            "keep",
            "retain",
            "review",
        }
        identity = json.dumps(
            [
                item.get("element"),
                item.get("ruleId"),
                None if held else item.get("action"),
            ],
            separators=(",", ":"),
        )
        group = groups.setdefault(
            identity,
            {
                "element": item.get("element"),
                "ruleId": item.get("ruleId"),
                "action": None if held else item.get("action"),
                "held": held,
                "count": 0,
                "ids": [],
                "reasons": {},
            },
        )
        group["count"] += 1
        if item.get("candidateAction") or not held:
            group["ids"].append(item["id"])
        if held:
            measurements = item.get("observations", {})
            confidence = measurements.get("confidence", measurements.get("conf"))
            tier = "规则例外候选" if item.get("status") == "exception" else "需专家裁定"
            if isinstance(confidence, (int, float)):
                reason = f"置信度{'≥0.8' if confidence >= 0.8 else '0.6–0.8' if confidence >= 0.6 else '<0.6'}，{tier}"
            else:
                reason = (
                    next(
                        (
                            label
                            for word, label in (
                                ("邻", "邻接关系待核对"),
                                ("拓扑", "拓扑关系待核对"),
                                ("面积", "面积规则待核对"),
                                ("缺", "证据不足"),
                            )
                            if word in item.get("reason", "")
                        ),
                        "规则判定",
                    )
                    + f"，{tier}"
                )
            group["reasons"][reason] = group["reasons"].get(reason, 0) + 1
    return {
        "total": len(suggestions),
        "groups": list(groups.values()),
        "suggestedIds": [
            item["id"]
            for item in suggestions
            if item.get("status") == "suggested"
            and item.get("action") not in {"keep", "retain", "review"}
        ],
        "candidateIds": [
            item["id"] for item in suggestions if item.get("candidateAction")
        ],
    }


def resolve_selection(plan, selection):
    from apps.compute.packages import ComputeError

    if (
        not isinstance(selection, dict)
        or set(selection) != {"base", "excludedIds", "includedIds"}
        or selection["base"] != "suggested"
    ):
        raise ComputeError("紧凑审批选择格式无效")
    for key in ("excludedIds", "includedIds"):
        values = selection[key]
        if (
            not isinstance(values, list)
            or any(
                not isinstance(value, str) or not 1 <= len(value) <= 64
                for value in values
            )
            or len(set(values)) != len(values)
        ):
            raise ComputeError("紧凑审批选择编号无效")
    index = review_index(plan.get("modificationReview", {}).get("suggestions", []))
    excluded, included = set(selection["excludedIds"]), set(selection["includedIds"])
    suggested, candidates = set(index["suggestedIds"]), set(index["candidateIds"])
    if excluded - suggested or included - candidates or excluded & included:
        raise ComputeError("紧凑审批选择超出本次冻结建议或候选范围", 409)
    selected = (suggested - excluded) | included
    return [
        item["id"]
        for item in plan.get("modificationReview", {}).get("suggestions", [])
        if item["id"] in selected
    ]


def compare_items(plan):
    review = plan.get("modificationReview") or {}
    approved = set(review.get("approvedSuggestionIds", []))
    suggestions = {
        _identity(item, True): item
        for item in review.get("suggestions", [])
        if item["id"] in approved
    }
    stage = next(
        (item for item in plan.get("stages", []) if item["name"] == "apply"), {}
    )
    actions = stage.get("modificationsApproval", {}).get("alterationActions", {})
    suggestions = {
        identity[:-1] + (actions.get(item.get("featureId"), item.get("action")),): {
            **item,
            "action": actions.get(item.get("featureId"), item.get("action")),
            "suggestedState": actions.get(
                item.get("featureId"), item.get("suggestedState", "")
            ),
        }
        for identity, item in suggestions.items()
    }
    result = next(
        (item for item in stage.get("results", []) if item.get("key") == "changes"), {}
    )
    rows = result.get("rows", [])
    if (
        stage.get("status") != "completed"
        or result.get("taskId") != stage.get("taskId")
        or result.get("scope") != "all"
        or result.get("rowCount") != len(rows)
        or not stage.get("taskId")
        or type(result.get("outputId")) is not int
        or result["outputId"] <= 0
        or not re.fullmatch(r"[a-f0-9]{64}", str(result.get("checksum", "")))
    ):
        return [], result
    edits = {}
    for edit in stage.get("approvedEdits", []):
        edits.setdefault(_identity(edit), []).append(edit)
    frequencies = Counter(
        _identity(row)
        for row in rows
        if str(row.get("actual_changed")).lower() in {"true", "1", "1.0"}
    )
    values = []
    for index, row in enumerate(rows):
        identity = _identity(row)
        suggestion = suggestions.get(identity)
        if (
            not suggestion
            or frequencies[identity] != 1
            or str(row.get("actual_changed")).lower() not in {"true", "1", "1.0"}
        ):
            continue
        if not any(
            str(edit.get("target_code", "")) == str(row.get("target_code", ""))
            and _same_weight(edit.get("weight"), row.get("weight"))
            and (
                not edit.get("snapshot_hash")
                or edit["snapshot_hash"] == row.get("snapshot_hash")
            )
            and (
                row.get("action") not in {"set_code", "reclassify", "merge"}
                or bool(edit.get("target_code"))
                and row.get("new_code") == edit["target_code"]
            )
            for edit in edits.get(identity, [])
        ):
            continue
        values.append((suggestion, {**row, "_rowIndex": index + 1}))
    values.sort(
        key=lambda pair: (
            {"lithology": 0, "structure": 1, "alteration": 2}.get(
                pair[0].get("element"), 3
            ),
            pair[0].get("ruleId", ""),
            pair[0].get("action", ""),
        )
    )
    return values, result


def _same_weight(left, right):
    try:
        return math.isfinite(float(left)) and float(left) == float(right)
    except (ValueError, TypeError):
        return False


def project_workflow(
    workflow, data, view, part, offset, limit, suggestion_id="", element="all"
):
    source = workflow.plan
    plan = {
        key: copy.deepcopy(source[key])
        for key in SUMMARY_KEYS
        if key in source and (view != "compare" or key != "fieldMappingReview")
    }
    plan["algorithms"] = {
        key: {
            "name": value.get("name"),
            "manifest": {
                "version": value.get("manifest", {}).get("version"),
                "outputs": [
                    {"key": output.get("key")}
                    for output in value.get("manifest", {}).get("outputs", [])
                ],
            },
        }
        for key, value in source.get("algorithms", {}).items()
    }
    plan["stages"] = [
        {key: stage[key] for key in STAGE_KEYS if key in stage}
        for stage in source.get("stages", [])
    ]
    if view == "compare":
        # Pages read spatial outputs by stage; identifiers only, no rows.
        for stage, original in zip(
            plan["stages"], source.get("stages", []), strict=True
        ):
            stage["results"] = [
                {
                    key: result.get(key)
                    for key in ("key", "kind", "taskId", "outputId", "checksum")
                }
                for result in original.get("results", [])
                if result.get("kind") == "vector"
            ]
    if view == "inspection":
        for key in (
            "reviewOutputs",
            "previousChange",
            "algorithm",
            "knowledgeSelection",
            "parameters",
            "previousAnalysis",
            "finalStage",
        ):
            if key in source:
                plan[key] = bounded(source[key])
        for stage, original in zip(
            plan["stages"], source.get("stages", []), strict=True
        ):
            for key in (
                "decision",
                "editValidation",
                "groupDecisions",
                "modelBudgetReview",
            ):
                if key in original:
                    stage[key] = bounded(original[key])
            stage["modelAttempts"] = [
                {
                    **{
                        key: attempt[key]
                        for key in (
                            "status",
                            "requested",
                            "inputTokens",
                            "window",
                            "contentBytes",
                            "budgetLevel",
                            "repairLevel",
                            "validationError",
                        )
                        if key in attempt
                    },
                    "responseSaved": bool(
                        attempt.get("responseArtifact") or attempt.get("response")
                    ),
                }
                for attempt in original.get("modelAttempts", [])[-1:]
            ]
    review = source.get("modificationReview")
    data.update(
        view=view,
        plan=plan,
        evidence=[],
        steps=[],
        parameters=bounded(workflow.parameters),
    )
    data.pop("modificationReview", None)
    page = {"part": part, "offset": offset, "limit": limit, "total": 0, "groups": []}
    plan["pagination"] = page
    if view == "compare":
        values, result = compare_items(source)
        from apps.knowledge.trial_rules import digest

        page["revision"] = digest(
            {
                "proposal": (source.get("modificationReview") or {}).get(
                    "proposalHash"
                ),
                "approved": (source.get("modificationReview") or {}).get(
                    "approvedSuggestionIds", []
                ),
                "output": {
                    key: result.get(key) for key in ("taskId", "outputId", "checksum")
                },
            }
        )
        counts = Counter(item.get("element", "") for item, _ in values)
        counts["all"] = len(values)
        page.update(
            element=element,
            counts={
                key: counts[key]
                for key in ("all", "lithology", "structure", "alteration")
            },
            alterationPixels=sum(
                int(float(row.get("pixel_count") or 0))
                for item, row in values
                if item.get("element") == "alteration"
            ),
            alterationAreaM2=sum(
                float(row.get("area_m2") or 0)
                for item, row in values
                if item.get("element") == "alteration"
            ),
        )
        if element != "all":
            values = [
                (item, row) for item, row in values if item.get("element") == element
            ]
        page["total"] = len(values)
        position = next(
            (
                position
                for position, (item, _) in enumerate(values)
                if item["id"] == suggestion_id
            ),
            None,
        )
        if position is not None:
            page["focusOffset"] = position // (limit or 25) * (limit or 25)
            offset = page["focusOffset"]
            page["offset"] = offset
        for position, (suggestion, _) in enumerate(values):
            key = json.dumps(
                [
                    suggestion.get("element"),
                    suggestion.get("ruleId"),
                    suggestion.get("action"),
                ],
                separators=(",", ":"),
            )
            if not page["groups"] or page["groups"][-1]["key"] != key:
                page["groups"].append(
                    {
                        "key": key,
                        "element": suggestion.get("element"),
                        "ruleId": suggestion.get("ruleId"),
                        "action": suggestion.get("action"),
                        "offset": position,
                        "count": 0,
                    }
                )
            page["groups"][-1]["count"] += 1
        selected = values[offset : offset + limit]
        suggestions = [
            {**item, "preview": display_preview(item.get("preview"))}
            for item, _ in selected
        ]
        actual_suggestions = suggestions
        if (
            review
            and not selected
            and limit
            and (
                source.get("phase") == "review_modifications"
                or getattr(workflow, "workflow_type", "geology_generic")
                == "geology_map_review"
            )
        ):
            candidates = review.get("suggestions", [])
            if suggestion_id:
                candidates = [
                    item for item in candidates if item["id"] == suggestion_id
                ]
            suggestions = [
                {**item, "preview": display_preview(item.get("preview"))}
                for item in candidates[offset : offset + limit]
            ]
        change_outputs = {
            output["key"]: output.get("resourceId")
            for stage in source.get("stages", [])
            if stage["name"] == "apply"
            for output in stage.get("outputs", [])
        }
        resource_keys = {
            "lithology": "changes_lithology_issues",
            "structure": "changes_fault_issues",
            "alteration": "changes_alteration_issues",
        }
        if review:
            data["modificationReview"] = {
                **{
                    key: value
                    for key, value in review.items()
                    if key
                    not in {
                        "suggestions",
                        "approvedSuggestionIds",
                        "unapprovedSuggestionIds",
                    }
                },
                "suggestions": suggestions,
                "approvedSuggestionIds": [item["id"] for item in actual_suggestions]
                or review.get("approvedSuggestionIds", [])[:1],
                "unapprovedSuggestionIds": [],
            }
        plan["compareFeatures"] = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": item["id"],
                    "geometry": item["preview"],
                    "properties": {
                        **row,
                        "display_resource_id": change_outputs.get(
                            resource_keys.get(item.get("element"))
                        ),
                    },
                }
                for item, (_, row) in zip(actual_suggestions, selected, strict=True)
            ],
        }
        for stage in plan["stages"]:
            if stage["name"] == "apply":
                stage["results"] = [
                    *stage.get("results", []),
                    {
                        **{
                            key: result.get(key)
                            for key in (
                                "key",
                                "taskId",
                                "outputId",
                                "checksum",
                                "scope",
                            )
                        },
                        "rows": [row for _, row in selected],
                        "rowCount": len(selected),
                    },
                ]
                identities = {_identity(row) for _, row in selected}
                stage["approvedEdits"] = [
                    edit
                    for edit in next(
                        item for item in source["stages"] if item["name"] == "apply"
                    ).get("approvedEdits", [])
                    if _identity(edit) in identities
                ]
        return data
    if review:
        suggestions = review.get("suggestions", [])
        position = next(
            (
                position
                for position, item in enumerate(suggestions)
                if item["id"] == suggestion_id
            ),
            None,
        )
        if part == "suggestions" and position is not None and limit:
            offset = position // limit * limit
            page["offset"] = offset
        plan["reviewIndex"] = review_index(suggestions)
        data["modificationReview"] = {
            **{key: value for key, value in review.items() if key != "suggestions"},
            "suggestions": [
                {**item, "preview": {"type": "Polygon", "coordinates": []}}
                for item in suggestions[offset : offset + limit]
            ]
            if part == "suggestions"
            else [],
        }
        if part == "suggestions":
            page["total"] = len(suggestions)
    if part == "steps":
        page["total"] = workflow.steps.count()
        data["steps"] = [
            {
                "id": item.id,
                "sequence": item.sequence,
                "kind": item.kind,
                "status": item.status,
                "message": item.message,
                "action": bounded(item.action),
                # Review steps store "approve"/"reject" here; only analysis
                # decisions are objects.
                "decision": (
                    bounded(item.action["decision"])
                    if isinstance(item.action.get("decision"), dict)
                    else None
                ),
                "inputRefs": bounded(item.input_refs),
                "outputRefs": (
                    item.output_refs
                    if item.kind == "analysis_model_attempt"
                    else bounded(item.output_refs)
                ),
                "metrics": bounded(item.metrics),
                "computeTaskId": str(item.compute_task_id or ""),
                "errorCode": item.error_code,
                "startedAt": item.started_at.isoformat(),
                "finishedAt": item.finished_at.isoformat() if item.finished_at else "",
            }
            for item in workflow.steps.order_by("sequence", "id")[
                offset : offset + limit
            ]
        ]
        data["evidence"] = bounded(workflow.evidence)
    return data
