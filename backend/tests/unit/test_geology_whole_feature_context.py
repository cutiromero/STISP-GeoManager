"""Topology-only evidence and one frozen review candidate per original polygon."""

from collections import Counter
import io
import json
from hashlib import sha256
from pathlib import Path
import runpy
import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import LineString, box


CORE = Path(__file__).resolve().parents[3] / "examples/compute/geology-multi-core"


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(CORE))
    import multi_checks
    import multi_context

    return multi_checks, multi_context


def context(rows, faults=()):
    lithology = gpd.GeoDataFrame(
        [(identity, code, code, shape) for identity, code, shape in rows],
        columns=["feature_id", "geo_sym", "name", "geometry"],
        geometry="geometry",
        crs=32646,
    )
    structures = gpd.GeoDataFrame(geometry=list(faults), crs=32646)
    return lithology, structures


INSIDE = box(1000, 1000, 2000, 2000)
COVERAGE = box(0, 0, 6000, 6000)


def rule(identifier, **params):
    return {
        "id": identifier,
        "version": "test",
        "knowledge_id": 1,
        "knowledge_revision": 1,
        "params": params,
    }


def test_missing_age_is_not_a_gate_and_review_uses_whole_original_geometry(modules):
    inspect, profile = modules
    materials, faults = context(
        [("one", "S", INSIDE), ("enclosure", "H", COVERAGE.difference(INSIDE))]
    )
    resolved = inspect.lithology_findings(
        materials,
        faults,
        COVERAGE,
        {"L-08": rule("L-08", context_strategy=profile.WHOLE_FEATURE_STRATEGY)},
        {},
        {},
        "frozen",
        {"working_epsg": 32646},
    )
    [finding] = resolved
    assert finding["_geometry"].equals(INSIDE)
    assert finding["feature_id"] == "one"
    assert finding["status"] == finding["suggested_action"] == "review"
    assert finding["candidate_action"] == "reclassify"
    assert finding["target_code"] == finding["candidate_target_code"] == "H"
    measurements = json.loads(finding["measurements_json"])
    assert measurements["context_relation"] is None
    assert measurements["shared_boundary_ratio"] == 1
    assert measurements["context_evidence"] == "isolated_same_unit"


def test_near_but_disconnected_same_unit_keeps_compact_patch_reviewable(modules):
    _, profile = modules
    peer = box(2200, 1000, 2500, 1400)
    materials, faults = context(
        [
            ("one", "S", INSIDE),
            ("peer", "S", peer),
            ("enclosure", "H", COVERAGE.difference(INSIDE.union(peer))),
        ]
    )
    candidates = list(
        profile.whole_feature_candidates(materials, faults, COVERAGE, {}, {})
    )
    [(source, target, evidence)] = [
        it for it in candidates if it[0].feature_id == "one"
    ]
    assert source.geometry.equals(INSIDE)
    assert target == "H"
    assert evidence["context_evidence"] == "closed_compact_contact"
    assert evidence["nearest_same_unit_m"] == 200


@pytest.mark.parametrize(
    "protection",
    ["same_contact", "fault_contact", "study_edge", "not_compact", "point"],
)
def test_context_protects_geological_continuity_and_noncontacts(modules, protection):
    _, profile = modules
    original = INSIDE
    coverage = COVERAGE
    faults = []
    rows = []
    exclusion = original
    if protection == "same_contact":
        peer = box(2000, 1200, 2400, 1300)
        rows.append(("peer", "S", peer))
        exclusion = original.union(peer)
    elif protection == "fault_contact":
        faults.append(LineString(list(original.exterior.coords)[:3]))
    elif protection == "study_edge":
        coverage = box(0, 1000, 6000, 6000)
    elif protection == "not_compact":
        original = exclusion = box(1000, 1000, 1050, 3000)
    elif protection == "point":
        coverage = box(2000, 2000, 6000, 6000)
    materials, structures = context(
        [("one", "S", original), ("host", "H", coverage.difference(exclusion)), *rows],
        faults,
    )
    assert all(
        row.feature_id != "one"
        for row, _, _ in profile.whole_feature_candidates(
            materials, structures, coverage, {}, {}
        )
    )


def test_chronology_becomes_evidence_without_duplicate_lithology_items(modules):
    inspect, profile = modules
    materials, faults = context(
        [("one", "S", INSIDE), ("host", "H", COVERAGE.difference(INSIDE))]
    )
    units = {
        "S": {"category": "stratum", "age_ma": 200},
        "H": {"category": "stratum", "age_ma": 100},
    }
    rules = {
        "L-01": rule("L-01"),
        "L-08": rule("L-08", context_strategy=profile.WHOLE_FEATURE_STRATEGY),
    }
    resolved = inspect.lithology_findings(
        materials, faults, COVERAGE, rules, units, {}, "frozen", {"working_epsg": 32646}
    )
    assert Counter(item["feature_id"] for item in resolved) == {"one": 1}
    [finding] = resolved
    assert finding["rule_id"] == "L-08"
    assert json.loads(finding["measurements_json"])["context_relation"] == "L-01"
    rules["L-08"]["params"].clear()
    legacy = inspect.lithology_findings(
        materials, faults, COVERAGE, rules, units, {}, "frozen", {"working_epsg": 32646}
    )
    assert [item["rule_id"] for item in legacy] == ["L-01"]


def test_invalid_threshold_does_not_silently_change_strategy(modules):
    _, profile = modules
    with pytest.raises(ValueError, match="dominant_boundary_min"):
        profile.whole_feature_parameters({"dominant_boundary_min": True})
    with pytest.raises(ValueError, match="强形态证据"):
        profile.whole_feature_parameters({"strong_contact_min": 0.80})


def test_missing_code_does_not_produce_an_unbound_target_or_stop_other_checks(modules):
    _, profile = modules
    other = box(3500, 1000, 4500, 2000)
    materials, faults = context(
        [
            ("missing", None, INSIDE),
            ("valid", "S", other),
            ("host", "H", COVERAGE.difference(INSIDE.union(other))),
        ]
    )
    [item] = list(profile.whole_feature_candidates(materials, faults, COVERAGE, {}, {}))
    assert item[0].feature_id == "valid" and item[1] == "H"


def test_pair_builder_changes_only_shared_check_and_metadata():
    builder = runpy.run_path(str(CORE / "build_vector_context.py"))
    for identifier in ("geology-multi-check", "geology-multi-apply"):
        original = io.BytesIO()
        baseline = {
            "identifier": identifier,
            "version": "1.0.0",
            "inputs": [{"key": "lithology"}],
        }
        with zipfile.ZipFile(original, "w") as package:
            package.writestr("operator.yaml", json.dumps(baseline))
            for name in builder["MODULES"]:
                package.writestr(name, "baseline")
            package.writestr("main.py", "entry")
            package.writestr("multi_apply.py", "unchanged vector geometry core")
        data = original.getvalue()
        base = builder["Baseline"](identifier, "1.0.0", sha256(data).hexdigest())
        result = builder["build"](base, data)
        with zipfile.ZipFile(io.BytesIO(result)) as package:
            assert package.read("main.py") == b"entry"
            assert package.read("multi_apply.py") == b"unchanged vector geometry core"
            assert (
                json.loads(package.read("operator.yaml"))["inputs"]
                == baseline["inputs"]
            )
            for name in builder["MODULES"]:
                assert package.read(name) == (CORE / name).read_bytes()
        with pytest.raises(ValueError, match="摘要不符"):
            builder["build"](base, data + b" ")
