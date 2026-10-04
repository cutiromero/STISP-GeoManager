import json
from types import SimpleNamespace

import pytest

from apps.compute.packages import ComputeError, validate_manifest
from apps.compute.quality import (
    MAX_REPORT_BYTES,
    quality_metadata,
    read_quality_report,
    require_automatic_quality,
)


def report(status="passed"):
    return {
        "version": 1,
        "status": status,
        "summary": "几何检查完成",
        "metrics": {"totalFeatures": 1, "needsReview": 0},
        "knowledgeFacts": {"geometryRepair": {"validAfter": 1}},
    }


def manifest():
    return {
        "schemaVersion": 1,
        "identifier": "checked",
        "name": "检查",
        "version": "1.0.0",
        "description": "计算检查",
        "author": "STISP",
        "runtime": "python-geospatial-v1",
        "inputs": [{"key": "source", "label": "输入", "kind": "vector"}],
        "parameters": [],
        "outputs": [
            {"key": "result", "label": "结果", "kind": "table", "file": "result.csv"}
        ],
        "qualityReport": {"file": "quality.json"},
    }


def test_quality_manifest_preserves_declaration():
    assert validate_manifest(manifest())["qualityReport"] == {"file": "quality.json"}


@pytest.mark.parametrize(
    "value",
    [
        {"file": "../outside.json"},
        {"file": "quality.txt"},
        {"file": "quality.json", "script": "run.py"},
        "quality.json",
        {"file": "C:\\outside.json"},
    ],
)
def test_quality_manifest_rejects_unsafe_or_extra_fields(value):
    with pytest.raises(ComputeError, match="qualityReport"):
        validate_manifest({**manifest(), "qualityReport": value})


def test_valid_report_propagates_quality_and_facts(tmp_path):
    value = report()
    (tmp_path / "quality.json").write_text(json.dumps(value), encoding="utf-8")
    loaded = read_quality_report(tmp_path, manifest())
    assert loaded == value
    metadata = quality_metadata(loaded)
    assert metadata["qualityCheck"]["status"] == "passed"
    assert metadata["knowledgeFacts"] == value["knowledgeFacts"]


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "invalid",
        '{"version":1,"version":1}',
        json.dumps({**report(), "status": "assumed_ok"}),
        json.dumps({**report(), "metrics": {"x": float("inf")}}),
        json.dumps({**report(), "summary": "x" * 2001}),
        " " * (MAX_REPORT_BYTES + 1),
    ],
    ids=[
        "missing",
        "invalid-json",
        "duplicate-key",
        "bad-status",
        "infinity",
        "long-summary",
        "oversize",
    ],
)
def test_missing_or_malformed_report_fails_closed_without_losing_outputs(tmp_path, raw):
    if raw is not None:
        (tmp_path / "quality.json").write_text(raw, encoding="utf-8")
    (tmp_path / "result.csv").write_text("x\n1\n", encoding="utf-8")
    loaded = read_quality_report(tmp_path, manifest())
    assert loaded["status"] == "needs_review"
    assert (tmp_path / "result.csv").read_text(encoding="utf-8") == "x\n1\n"


def output(metadata, *, declared=True):
    return SimpleNamespace(
        task=SimpleNamespace(
            version=SimpleNamespace(manifest=manifest() if declared else {})
        ),
        metadata=metadata,
    )


def test_automatic_import_requires_pass_for_declared_checks():
    require_automatic_quality(output(quality_metadata(report())))
    require_automatic_quality(output({}, declared=False))
    for metadata in (
        {},
        quality_metadata(report("needs_review")),
        {"qualityCheck": {"status": "passed"}},
    ):
        with pytest.raises(ComputeError, match="自动入库"):
            require_automatic_quality(output(metadata))


def test_deep_json_is_rejected_without_recursion_failure(tmp_path):
    value = report()
    nested = {}
    value["metrics"] = nested
    for _ in range(15):
        nested["next"] = {}
        nested = nested["next"]
    (tmp_path / "quality.json").write_text(json.dumps(value), encoding="utf-8")
    assert read_quality_report(tmp_path, manifest())["status"] == "needs_review"
