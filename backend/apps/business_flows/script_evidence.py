"""Small, version-bound source facts; no new file hashes or geometry decoding."""

from copy import deepcopy

from django.core.exceptions import ValidationError

from apps.compute.data import list_candidate
from apps.compute.packages import ComputeError
from apps.agent.tools import frame, clean

MAX_TEXT_CHARACTERS = 4000
SAMPLE_ROWS = 4
MAX_FIELDS = 20
MAX_SAMPLE_FIELDS = 10
TEXT_FORMATS = {
    "TXT",
    "MD",
    "JSON",
    "FA",
    "FASTA",
    "FNA",
    "GFF",
    "GFF3",
    "VCF",
    "FASTQ",
    "FQ",
    "CSV",
    "TSV",
}


def evidence(workflow, resources, bindings):
    cache = workflow.plan.setdefault("inputScriptEvidence", {})
    result = []
    by_id = {resource.pk: resource for resource in resources}
    for port, identity in bindings.items():
        resource = by_id[identity]
        key = str(resource.pk) + ":" + resource.updated_at.isoformat()
        item = cache.get(key)
        if (
            not isinstance(item, dict)
            or item.get("id") != resource.pk
            or item.get("revision") != resource.updated_at.isoformat()
        ):
            metadata = workflow.plan.get("inputPreparationSchemas", {}).get(
                key
            ) or list_candidate(resource)
            item = {
                "id": resource.pk,
                "revision": resource.updated_at.isoformat(),
                "name": resource.name,
                "sourceType": resource.data_type,
                "originalFileFormat": resource.file_format,
                "snapshotFormat": {
                    "table": "CSV",
                    "vector": "GeoPackage",
                    "raster": "GeoTIFF",
                }.get(resource.data_type, resource.file_format),
                "fields": metadata.get("fields", [])[:MAX_FIELDS],
                "fieldCount": len(metadata.get("fields", [])),
                "fieldListComplete": len(metadata.get("fields", [])) <= MAX_FIELDS,
                "bands": metadata.get("bands", 0),
                "crs": metadata.get("crs", ""),
                "geometryTypes": metadata.get("geometryTypes", []),
                "sizeBytes": metadata.get("sizeBytes", resource.size_bytes),
                "catalogItemCount": resource.item_count,
                "description": resource.description[:1000],
                "contentScope": "metadata",
            }
            if resource.data_type in {"table", "vector"}:
                try:
                    data, info = frame(resource, limit=SAMPLE_ROWS)
                    columns = list(data.columns)[:MAX_SAMPLE_FIELDS]
                    item.update(
                        sample=clean(data[columns].to_dict("records")),
                        sampleScope=info["scope"],
                        sampleRowLimit=SAMPLE_ROWS,
                        sampleFieldLimit=MAX_SAMPLE_FIELDS,
                        contentScope="bounded_attribute_sample",
                    )
                except (ValidationError, ComputeError, OSError, ValueError) as error:
                    item["sampleUnavailable"] = str(error)[:200]
            elif resource.data_type in {"gene", "document"}:
                from apps.catalog.nongeo import _resource_file_path

                path = _resource_file_path(resource, analysis_limit=False)
                item["snapshotExtension"] = path.suffix
                if (
                    resource.file_format.upper() in TEXT_FORMATS
                    or path.suffix.lower().lstrip(".").upper() in TEXT_FORMATS
                ):
                    with path.open(encoding="utf-8-sig", errors="replace") as stream:
                        text = stream.read(MAX_TEXT_CHARACTERS + 1)
                    item.update(
                        textSample=text[:MAX_TEXT_CHARACTERS],
                        sampleScope="text_prefix",
                        sampleTruncated=len(text) > MAX_TEXT_CHARACTERS,
                        contentScope="bounded_text_sample",
                    )
            cache[key] = deepcopy(item)
        result.append(
            {
                "id": "source-" + str(resource.pk) + "-" + port,
                "kind": "resource",
                "title": resource.name,
                "result": {**deepcopy(item), "inputPort": port},
            }
        )
    return result
