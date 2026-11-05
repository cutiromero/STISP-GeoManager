"""Inspect three actual input elements using explicitly bound trial knowledge."""

from multi_checks import inspect, issue_maps
from multi_io import (
    ISSUE_FIELDS,
    inputs,
    report,
    settings,
    write_table,
    write_vector,
)
from multi_raster import RasterAlterations, empty_vectors


def run(context):
    config = settings(context)
    lithology, faults, area, rules, units, aliases, snapshot = inputs(context, config)
    alterations = RasterAlterations(context, config, area)
    findings, alterations = inspect(
        lithology, faults, alterations, area, rules, units, aliases, snapshot, config
    )
    write_table(context.output_path("issues.csv"), findings, ISSUE_FIELDS)
    issue_maps(context, findings, config)
    alterations.outputs(context)
    write_vector(
        context.output_path("alterations.gpkg"),
        empty_vectors(config["working_epsg"]),
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
        "alteration_pixel_count": sum(
            row["original_pixels"] for row in alterations.quality
        ),
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
        f"检查{len(lithology)}个岩性图斑、{len(faults)}条构造及{metrics['alteration_pixel_count']}个矿物像元，发现{len(findings)}条可核查建议（蚀变按组计数）；尚未修改资料。",
    )
