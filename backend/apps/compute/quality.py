"""Bounded, declarative algorithm quality reports and automatic import gates."""

import json
import math

from .packages import ComputeError

MAX_REPORT_BYTES = 64 * 1024


def _validate_json(value, depth=0, remaining=None):
    if remaining is None:
        remaining = [10000]
    remaining[0] -= 1
    if depth > 12 or remaining[0] < 0:
        raise ValueError("质量报告结构过大或层级过深")
    if value is None or type(value) is bool:
        return
    if isinstance(value, str):
        if len(value) > 8000 or "\x00" in value:
            raise ValueError("质量报告文字过长或包含无效字符")
        return
    if type(value) in {float, int}:
        if not math.isfinite(value):
            raise ValueError("质量报告包含非有限数字")
        return
    if isinstance(value, list):
        for child in value:
            _validate_json(child, depth + 1, remaining)
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or not key or len(key) > 160 or "\x00" in key:
                raise ValueError("质量报告包含无效字段名")
            _validate_json(child, depth + 1, remaining)
        return
    raise ValueError("质量报告包含非JSON值")


def validate_report(report):
    if not isinstance(report, dict) or set(report) != {
        "version",
        "status",
        "summary",
        "metrics",
        "knowledgeFacts",
    }:
        raise ValueError("质量报告字段不完整或含未声明字段")
    if type(report["version"]) is not int or report["version"] != 1:
        raise ValueError("质量报告版本不支持")
    if report["status"] not in {"passed", "needs_review"}:
        raise ValueError("质量报告状态无效")
    summary = report["summary"]
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 2000:
        raise ValueError("质量报告摘要须为1至2000字")
    if not isinstance(report["metrics"], dict) or not isinstance(
        report["knowledgeFacts"], dict
    ):
        raise ValueError("质量报告指标与知识事实须为对象")
    _validate_json(report)
    return report


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("质量报告字段重复")
        result[key] = value
    return result


def read_quality_report(directory, manifest):
    spec = manifest.get("qualityReport")
    if not spec:
        return None
    try:
        path = directory / spec["file"]
        if path.is_symlink() or not path.is_file():
            raise ValueError("算法声明的质量报告缺失")
        with path.open("rb") as stream:
            raw = stream.read(MAX_REPORT_BYTES + 1)
        if len(raw) > MAX_REPORT_BYTES:
            raise ValueError("质量报告超过64 KiB")
        report = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object)
        return validate_report(report)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError, OSError):
        return {
            "version": 1,
            "status": "needs_review",
            "summary": "质量报告缺失或无效，自动入库已暂停；请检查算法输出与审核材料。",
            "metrics": {},
            "knowledgeFacts": {},
        }


def quality_metadata(report):
    if report is None:
        return {}
    return {
        "qualityCheck": {
            key: value for key, value in report.items() if key != "knowledgeFacts"
        },
        "knowledgeFacts": report["knowledgeFacts"],
    }


def require_automatic_quality(output):
    """Never treat missing evidence from a declared check as a pass."""
    declared = bool(output.task.version.manifest.get("qualityReport"))
    check = output.metadata.get("qualityCheck")
    if check is None and not declared:
        return
    try:
        report = {**check, "knowledgeFacts": output.metadata.get("knowledgeFacts", {})}
        validate_report(report)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ComputeError(
            "质量核查证据缺失或无效，已保留结果并暂停自动入库", 409
        ) from exc
    if report["status"] != "passed":
        raise ComputeError(
            "结果需要审核，已保留原始输出并暂停自动入库：" + report["summary"], 409
        )
