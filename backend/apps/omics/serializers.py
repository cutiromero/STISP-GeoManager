from __future__ import annotations

from apps.ecology.serializers import serialize_site_summary, serialize_taxon_summary
from apps.omics.models import GermplasmAccession


def serialize_germplasm_accession(accession: GermplasmAccession) -> dict:
    biological_sample = accession.biological_sample
    taxon = accession.taxon or (
        biological_sample.taxon if biological_sample is not None else None
    )
    source_site = accession.source_site or (
        biological_sample.source_site if biological_sample is not None else None
    )
    sample_code = accession.sample_code or (
        biological_sample.sample_code if biological_sample is not None else ""
    )
    material_type = accession.material_type or (
        biological_sample.material_type if biological_sample is not None else ""
    )
    sex = accession.sex or (biological_sample.sex if biological_sample is not None else "")
    return {
        "id": accession.id,
        "accessionCode": accession.accession_code,
        "sampleCode": sample_code,
        "taxon": serialize_taxon_summary(taxon),
        "sourceSite": serialize_site_summary(source_site),
        "materialType": material_type,
        "resourceType": accession.resource_type,
        "sex": sex,
        "isCore": accession.is_core,
        "storageStatus": accession.storage_status,
        "sourceResourceId": accession.source_resource_id,
        "createdAt": accession.created_at.isoformat(),
        "updatedAt": accession.updated_at.isoformat(),
    }
