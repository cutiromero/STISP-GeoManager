from copy import deepcopy

import pytest

from apps.agent.demo_results import result_evidence


def test_display_projection_keeps_all_scientific_metadata_and_original_snapshot():
    stored = [
        {
            "kind": "raster",
            "checksum": "original",
            "rows": [],
            "metadata": {
                "crs": "EPSG:32646",
                "bands": 1,
                "qualityCheck": {
                    "passed": True,
                    "colorAdvice": "scientific nested value",
                },
            },
        }
    ]
    current = deepcopy(stored)
    current[0]["metadata"].update(
        mapColorTable={"version": 1}, colorAdvice={"source": "model_validated"}
    )
    snapshot = deepcopy(current)
    assert result_evidence(stored) == result_evidence(current)
    assert current == snapshot
    current[0]["metadata"]["qualityCheck"]["colorAdvice"] = "changed"
    assert result_evidence(stored) != result_evidence(current)


@pytest.mark.parametrize("kind", ["table", "vector", "archive"])
def test_other_output_types_keep_metadata_even_when_names_match_display_keys(kind):
    stored = [{"kind": kind, "metadata": {"colorAdvice": "initial"}}]
    current = [{"kind": kind, "metadata": {"colorAdvice": "changed"}}]
    assert result_evidence(stored) != result_evidence(current)
