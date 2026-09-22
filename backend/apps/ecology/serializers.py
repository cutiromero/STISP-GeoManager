from __future__ import annotations

from apps.ecology.models import Site, Taxon


def serialize_taxon_summary(taxon: Taxon | None) -> dict | None:
    if taxon is None:
        return None
    return {
        "id": taxon.id,
        "nameCn": taxon.name_cn,
        "scientificName": taxon.scientific_name,
    }


def serialize_site_summary(site: Site | None) -> dict | None:
    if site is None:
        return None
    return {
        "id": site.id,
        "name": site.name,
        "longitude": site.longitude,
        "latitude": site.latitude,
        "altitude": site.altitude,
    }
