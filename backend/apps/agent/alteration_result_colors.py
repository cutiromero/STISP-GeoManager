"""One audited model palette per workflow, shared by binary mineral rasters."""

import json

from apps.audit.service import log_operation
from apps.compute.models import ComputeOutput

from . import provider
from .result_colors import category_style, model_colors, proposal_items
from .color_library import policy_revision


MINERALS = {
    "hematite": "赤铁矿化",
    "chlorite": "绿泥石化",
    "hydromica": "水云母化",
    "calcite": "方解石化",
    "dolomite": "白云石化",
}
TABLE_VERSION = 1


def mineral_key(output):
    mineral, _, suffix = output.key.rpartition("_")
    return (
        mineral
        if output.kind == "raster"
        and mineral in MINERALS
        and suffix in {"before", "corrected"}
        else None
    )


def style_alteration_outputs(workflow, outputs, *, force=False, persist=True):
    targets = [output for output in outputs if mineral_key(output)]
    if not targets:
        return []
    previous = list(
        ComputeOutput.objects.filter(pk__in=workflow.result_ids, kind="raster")
    )
    tables = {
        mineral_key(output): output.metadata["mapColorTable"]
        for output in [*previous, *targets]
        if mineral_key(output)
        and output.metadata.get("mapColorTable", {}).get("version") == TABLE_VERSION
        and output.metadata.get("mapColorTable", {}).get("policyRevision")
        == policy_revision()
    }
    if force:
        tables = {}
    missing = sorted({mineral_key(output) for output in targets} - tables.keys())
    advice = None
    if missing:
        proposal, failure = None, ""
        try:
            proposal = model_colors(workflow, "mineral", list(MINERALS))
        except (provider.ModelError, OSError, ValueError, KeyError, TypeError):
            failure = "model_unavailable_or_invalid"
        records = []
        style, replaced = category_style(
            "mineral", list(MINERALS), proposal, audit=records
        )
        _, issues = proposal_items("mineral", list(MINERALS), proposal)
        advice = {
            "source": "model_validated" if proposal and not issues else "deterministic",
            "proposal": proposal,
            "classes": records,
            "issues": issues,
            "replaced": replaced,
            "failure": failure,
        }
        colors = {item["value"]: item["color"] for item in style["renderer"]["classes"]}
        for mineral in missing:
            tables[mineral] = {
                "version": TABLE_VERSION,
                "policyRevision": policy_revision(),
                "mineral": mineral,
                "source": advice["source"],
                "classes": [
                    {"value": 0, "label": "无蚀变", "color": "#00000000"},
                    {
                        "value": 1,
                        "label": MINERALS[mineral],
                        "color": colors[mineral] + "ff",
                    },
                ],
            }
    result = []
    for output in targets:
        table = tables[mineral_key(output)]
        metadata = {**output.metadata, "mapColorTable": table}
        if advice:
            metadata["colorAdvice"] = advice
        if persist and metadata != output.metadata:
            output.metadata = metadata
            output.save(update_fields=["metadata"])
        result.append({"outputId": output.id, "mapColorTable": table})
    if persist and advice:
        log_operation(
            workflow.owner,
            "agent",
            "alteration_color_advice",
            "success",
            json.dumps(
                {"workflowId": str(workflow.id), "outputs": result, **advice},
                ensure_ascii=False,
            ),
            target_type="agent_workflow",
            target_code=str(workflow.id),
        )
    return result
