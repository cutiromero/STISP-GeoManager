"""Published output selection for completed business flows."""

from apps.compute.models import ComputeImport, ComputeOutput


def evidence_output_id(value):
    if isinstance(value, str) and value.startswith("output-") and value[7:].isdigit():
        return int(value[7:])
    return None


def consumed_deliverables(workflow, value, *, already_saved=()):
    """Retain contracted final outputs also used as inputs by another node."""
    candidates = set(value.get("consumedOutputs", [])) - set(already_saved)
    if not candidates:
        return set()
    contracted = {
        identity
        for node in value["nodes"].values()
        if node.get("status") == "succeeded"
        for row in node.get("contractOutputs", [])
        if (identity := evidence_output_id(row.get("evidenceId"))) in candidates
    }
    if not contracted:
        return set()
    outputs = ComputeOutput.objects.filter(
        pk__in=contracted,
        task_id__in=workflow.steps.exclude(compute_task_id=None).values(
            "compute_task_id"
        ),
        task__owner_id=workflow.owner_id,
        task__project_tag_id=workflow.project_tag_id,
        task__status="succeeded",
        task__trial=False,
    ).values_list("pk", "key", "task__version__manifest")
    return {
        identity
        for identity, key, manifest in outputs
        if any(
            spec["key"] == key and spec.get("final") is True
            for spec in manifest.get("outputs", [])
        )
    }


def completed_output_ids(workflow, value):
    outputs = {
        identity
        for node in value["nodes"].values()
        for row in node.get("outputs", {}).get("evidence", [])
        if (identity := evidence_output_id(row.get("id"))) is not None
    }
    consumed = set(value.get("consumedOutputs", []))
    deliverables = consumed_deliverables(workflow, value)
    return sorted(outputs - (consumed - deliverables))


def imported_resource_ids(output_ids):
    return list(
        ComputeImport.objects.filter(output_id__in=output_ids, status="ready")
        .exclude(resource_id=None)
        .values_list("resource_id", flat=True)
    )
