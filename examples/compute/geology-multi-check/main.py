"""Inspect three actual input elements using explicitly bound trial knowledge."""

from multi_checks import inspect, issue_maps
from multi_io import (
    ISSUE_FIELDS,
    inputs,
    load_alterations,
    report,
    settings,
    write_table,
    write_vector,
)


def run(context):
    config = settings(context)
    lithology, faults, area, rules, units, aliases, snapshot = inputs(context, config)
    alterations, snapshot = load_alterations(context, config, area, snapshot)
    findings, alterations = inspect(
        lithology, faults, alterations, area, rules, units, aliases, snapshot, config
    )
    write_table(context.output_path("issues.csv"), findings, ISSUE_FIELDS)
    issue_maps(context, findings, config)
    write_vector(
        context.output_path("alterations.gpkg"),
        alterations,
        config["working_epsg"],
        "MultiPolygon",
    )
    counts = [
        {
            "rule_id": key,
            "rule_version": rule["version"],
            "issue_count": sum(row["rule_id"] == key for row in findings),
            "knowledge_id": rule["knowledge_id"],
            "knowledge_revision": rule["knowledge_revision"],
        }
        for key, rule in sorted(rules.items())
    ]
    write_table(
        context.output_path("statistics.csv"),
        counts,
        [
            "rule_id",
            "rule_version",
            "issue_count",
            "knowledge_id",
            "knowledge_revision",
        ],
    )
    metrics = {
        "lithology_count": len(lithology),
        "fault_count": len(faults),
        "alteration_count": len(alterations),
        "issue_count": len(findings),
        "suggested_count": sum(row["status"] == "suggested" for row in findings),
        "review_count": sum(row["status"] == "review" for row in findings),
        "exception_count": sum(row["status"] == "exception" for row in findings),
        "snapshot_hash": snapshot,
        "rule_count": len(rules),
        "rule_versions": {key: row["version"] for key, row in rules.items()},
        "working_epsg": config["working_epsg"],
        "reference_used": False,
        "map_modified": False,
    }
    report(
        context,
        metrics,
        f"检查{len(lithology)}个岩性图斑、{len(faults)}条构造及{len(alterations)}处矿物识别范围，发现{len(findings)}条可核查建议；尚未修改资料。",
    )
