"""Separate independently reviewed reference maps from correction inputs."""

REFERENCE_SOURCE_PREFIX = "geology-case-reference-20261012:"
MATERIAL_SOURCE_PREFIX = "geology-case-20261012:"


def is_reference_resource(resource):
    return (resource.source or "").startswith(REFERENCE_SOURCE_PREFIX)
