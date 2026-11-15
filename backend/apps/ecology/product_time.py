"""Observation dates follow input snapshots; ingestion timestamps stay separate."""

from apps.catalog.models import ResourceObservationMetadata
from apps.catalog.monitoring_metadata import period_payload, update_metadata


def input_periods(task):
    records = list(task.input_records.exclude(resource=None).order_by("pk"))
    current = {
        row.resource_id: period_payload(row)
        for row in ResourceObservationMetadata.objects.filter(
            resource_id__in=[record.resource_id for record in records]
        )
    }
    return [
        record.snapshot.get("observationPeriod") or current.get(record.resource_id)
        for record in records
    ]


def interval(periods):
    if not periods or any(
        not row or not row.get("startsAt") or not row.get("endsAt") for row in periods
    ):
        return None, None
    return min(row["startsAt"] for row in periods), max(
        row["endsAt"] for row in periods
    )


def record_import_metadata(record_id):
    from apps.compute.models import ComputeImport

    record = ComputeImport.objects.select_related(
        "output__task__version__algorithm", "resource", "requested_by"
    ).get(pk=record_id)
    task = record.output.task
    identifier = task.version.algorithm.identifier
    scene = {
        "spartina-rf-infer": "spartina",
        "wildfire-observe": "wildfire",
        "landcover-unet-infer": "landcover",
    }.get(identifier)
    if not scene or record.status != "ready" or not record.resource_id:
        return
    if scene == "wildfire":
        current = (
            record.output.metadata.get("knowledgeFacts", {})
            .get("wildfireObservation", {})
            .get("current", {})
        )
        begin, end = current.get("observedStart"), current.get("observedEnd")
    else:
        begin, end = interval(input_periods(task))
    update_metadata(
        record.requested_by,
        record.resource,
        {
            "family": "result",
            "collectionKey": f"monitor-{scene}",
            "precision": "interval" if begin and end else "unknown",
            "startsAt": begin,
            "endsAt": end,
            "usages": [{"scene": scene, "purpose": "result"}],
        },
        require_edit=False,
    )


def attach_observation_periods(items, periods=None):
    identities = {
        identity
        for item in items
        for identity in [item["resourceId"], *item["sourceResourceIds"]]
    }
    if periods is None:
        periods = {
            row.resource_id: period_payload(row)
            for row in ResourceObservationMetadata.objects.filter(
                resource_id__in=identities
            )
        }
    for item in items:
        direct = periods.get(item["resourceId"])
        if direct and direct.get("startsAt"):
            item["observedStart"], item["observedEnd"] = (
                direct["startsAt"],
                direct["endsAt"],
            )
        elif (
            item["scene"] == "spartina"
            and item.get("extraction")
            and not item["observedStart"]
        ):
            begin, end = interval(
                [periods.get(identity) for identity in item["sourceResourceIds"]]
            )
            if begin and end:
                item["observedStart"], item["observedEnd"] = begin, end
