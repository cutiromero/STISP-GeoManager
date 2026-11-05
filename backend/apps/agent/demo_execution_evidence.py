"""Lossless facts for later decisions, without repeated proposal or render details."""

import hashlib
import json


# Configuration: only the frozen multi-element graph's later decisions use this view.
EXECUTION_STAGES = {
    "recheck": "geology-multi-check",
    "relations": "geology-multi-relations",
    "prospect": "geology-multi-prospect",
    "final_analysis": "finish",
}
FACT_KEYS = {
    "statistics",
    "changes",
    "alteration_quality",
    "alteration_summary",
    "evidence",
}
QUALITY_KEYS = {
    "qualityCheck",
    "qualityCheckRef",
    "knowledgeFacts",
    "knowledgeFactsRef",
    "quality",
    "validation",
    "warning",
    "warnings",
    "error",
    "errors",
    "status",
}


def execution_evidence_scope(payload):
    return (
        "upstreamVersions" in payload
        and payload.get("stage") in EXECUTION_STAGES
        and EXECUTION_STAGES[payload["stage"]] == payload.get("allowedAction")
    )


def execution_fact_paths(payload):
    """Derive exemptions from the frozen graph, never from a supplied marker."""
    if not execution_evidence_scope(payload):
        return set()
    paths = set()
    for index, item in enumerate(payload.get("actualResults", [])):
        if item.get("key") in FACT_KEYS:
            base = f"actualResults[{index}]"
            paths.update(
                {
                    f"{base}.rows",
                    f"{base}.aggregate.byPhaseAndGrade",
                    f"{base}.aggregate.evidenceCombinations",
                    f"{base}.aggregate.evidenceCombinations.rows",
                }
            )
    paths.update({"modificationReview.groups", "modificationReview.groups.rows"})
    return paths


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _quality(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in QUALITY_KEYS:
                result[key] = item
            elif isinstance(item, (dict, list)):
                nested = _quality(item)
                if nested:
                    result[key] = nested
        return result
    if isinstance(value, list):
        # Preserve positions when a nested quality entry occurs inside a list.
        values = [_quality(item) for item in value]
        return values if any(values) else []
    return None


def _column_rows(rows, columns=None):
    if not rows or not all(isinstance(row, dict) for row in rows):
        return None
    columns = list(columns or rows[0])
    if any(set(row) != set(columns) for row in rows):
        return None
    return {
        "columns": columns,
        "rows": [[row[name] for name in columns] for row in rows],
        "rowFormat": "columns",
    }


def _approval_groups(groups):
    """Preserve every group, cell and source position, including absent cells."""
    if not isinstance(groups, list) or not all(isinstance(row, dict) for row in groups):
        return groups
    values = []
    for row in groups:
        row = dict(row)
        count, approved = row.get("count"), row.get("approvedCount")
        if type(count) is int and type(approved) is int and 0 <= approved <= count:
            row["unapprovedCount"] = count - approved
        values.append(row)
    columns = list(dict.fromkeys(key for row in values for key in row))
    return {
        "columns": columns,
        "rows": [[row.get(name) for name in columns] for row in values],
        "absentColumns": [
            [index for index, name in enumerate(columns) if name not in row]
            for row in values
        ],
        "rowFormat": "columns",
        "groupCount": len(values),
        "scope": "all_groups",
    }


def project_execution_evidence(payload, level):
    """Mutate only the projection copy; complete sources stay in the stage audit."""
    if level < 2 or not execution_evidence_scope(payload):
        return payload
    source = payload.get("actualResults", [])
    reference_only = []
    for item in source:
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            item["metadata"] = _quality(metadata)
        item.pop("checksum", None)
        item.pop("samplingNote", None)
        if item.get("key") in FACT_KEYS:
            packed = _column_rows(item.get("rows", []), item.get("columns"))
            if packed:
                item.update(packed)
        elif not item.get("rows") and not item.get("groups"):
            reference_only.append(item.get("outputId"))
            item.pop("columns", None)
    omitted = {str(identity) for identity in reference_only}
    if "availableEvidence" in payload:
        payload["availableEvidence"] = [
            {key: value for key, value in ref.items() if key != "title"}
            for ref in payload["availableEvidence"]
            if ref.get("kind") != "output" or str(ref.get("id")) not in omitted
        ]
    review = payload.get("modificationReview")
    if isinstance(review, dict):
        review["groups"] = _approval_groups(review.get("groups"))
        count, approved = review.get("suggestionCount"), review.get("approvedCount")
        if type(count) is int and type(approved) is int and 0 <= approved <= count:
            review["unapprovedCount"] = count - approved
        if any(item.get("key") == "changes" for item in source):
            suggestions = review.pop("suggestions", None)
            if suggestions is not None:
                review["historicalSuggestions"] = {
                    "sourceSha256": _digest(suggestions),
                    "scope": "reference_only",
                    "note": "历史方案代表明细与长理由保存在原批准方案；本次未重新展示或逐对象审阅。",
                }
    algorithm = payload.get("allowedAlgorithm", {})
    manifest = algorithm.get("manifest")
    if isinstance(manifest, dict):
        algorithm["manifest"] = {
            key: value
            for key, value in manifest.items()
            if key in {"identifier", "name", "version", "parameters"}
        }
    payload["executionEvidenceProjection"] = {
        "scope": "complete_read_facts_and_approval_groups",
        "referenceOnlyOutputIds": reference_only,
        "note": (
            "statistics、changes、质量与聚合汇总保留全部已读取行，不能把源代表样本称为全量对象审阅。"
            "输出身份为outputId/taskId/key/kind，完整文件、渲染头、来源指纹和算法契约保存在阶段审计。"
            "referenceOnlyOutputIds仅提供身份和显示的质量信息，未展示文件内容不能作为判断依据。"
            "质量Ref按outputId及path读取本次actualResults中的原值。当前是否已计算以executionState为准。"
            "批准仅指modificationReview的原方案；groups列式表保留全部组的批准/未批准计数，"
            "absentColumns按每行从0起的列索引标记原先不存在的字段，不能将其占位null当成实测。"
            "批准数量不等于实际改变，须分别读取changes的count/actualChanged及真实统计。"
        ),
    }
    return payload
