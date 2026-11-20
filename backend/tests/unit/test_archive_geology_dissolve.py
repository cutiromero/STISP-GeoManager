import json
from pathlib import Path
import runpy

import geopandas as gpd
import pytest
from shapely import box, unary_union


CORE = Path(__file__).resolve().parents[3] / "examples/compute/geology-multi-core"
dissolve = runpy.run_path(str(CORE / "archive_dissolve.py"))[
    "dissolve_archive_additions"
]


def partition(*items):
    return gpd.GeoDataFrame(
        [
            {
                "feature_id": identity,
                "geo_sym": code,
                "name": identity,
                "geometry": geom,
            }
            for identity, code, geom in items
        ],
        crs=32646,
    )


def approved(identity, geom, target="U002"):
    return {
        "feature_id": identity,
        "action": "reclassify",
        "actual_changed": True,
        "new_code": target,
        "_geometry": geom,
        "class_change_area_m2": geom.area,
        "host_feature_id": "",
        "absorbed_ids": "[]",
        "removed_internal_boundary_m": 0.0,
    }


def test_partial_approval_fuses_same_class_shared_edge_but_keeps_residual_class():
    changed, retained, host = box(1, 0, 2, 2), box(0, 0, 1, 2), box(2, 0, 4, 2)
    before = partition(
        ("F-old", "U001", retained),
        ("F-host", "U002", host),
        ("A-U002", "U002", changed),
    )
    proof = approved("AR-1", changed)
    result = dissolve(before, [proof]).set_index("feature_id")
    assert set(result.index) == {"F-old", "F-host"}
    assert retained.equals(result.at["F-old", "geometry"])
    assert result.at["F-old", "geo_sym"] == "U001"
    assert result.at["F-host", "geometry"].equals(box(1, 0, 4, 2))
    assert result.at["F-host", "name"] == "F-host"
    assert proof["host_feature_id"] == "F-host"
    assert proof["removed_internal_boundary_m"] == pytest.approx(2)
    assert proof["class_change_area_m2"] == 2
    assert proof["_geometry"].equals(changed)


def test_bridge_joins_receivers_once_but_point_and_distant_neighbours_stay_separate():
    left, right = box(0, 0, 2, 2), box(4, 0, 6, 2)
    p1, p2 = box(2, 0, 3, 2), box(3, 0, 4, 2)
    corner, remote = box(6, 2, 7, 3), box(20, 20, 21, 21)
    before = partition(
        ("F-a", "U002", left),
        ("F-b", "U002", right),
        ("F-corner", "U002", corner),
        ("F-remote", "U002", remote),
        ("A-U002", "U002", unary_union([p1, p2])),
    )
    audit = [approved("AR-1", p1), approved("AR-2", p2)]
    result = dissolve(before, audit).set_index("feature_id")
    assert list(result.index) == ["F-a", "F-corner", "F-remote"]
    assert result.at["F-a", "geometry"].equals(box(0, 0, 6, 2))
    assert result.at["F-corner", "geometry"].equals(corner)
    assert result.at["F-remote", "geometry"].equals(remote)
    assert all(row["host_feature_id"] == "F-a" for row in audit)
    assert json.loads(audit[0]["absorbed_ids"]) == ["F-b"]
    assert sum(row["removed_internal_boundary_m"] for row in audit) == pytest.approx(4)
    assert unary_union(result.geometry.to_numpy()).equals(
        unary_union(before.geometry.to_numpy())
    )


def test_standalone_patch_and_unmatched_clipped_target_are_not_fabricated_as_merged():
    patch, corner = box(0, 0, 2, 2), box(2, 2, 4, 4)
    before = partition(("A-U002", "U002", patch), ("F-corner", "U002", corner))
    audit = approved("AR-1", patch, target="U002 / U003")
    assert dissolve(before, [audit]) is before
    assert not audit["host_feature_id"] and audit["removed_internal_boundary_m"] == 0


def test_multipart_hosts_do_not_connect_unrelated_components():
    from shapely import MultiPolygon

    left, right = box(-1, 0, 1, 2), box(19, 0, 21, 2)
    a, b = box(1, 0, 2, 2), box(21, 0, 22, 2)
    multipart = MultiPolygon([box(2, 0, 3, 2), box(22, 0, 23, 2), box(50, 0, 51, 2)])
    before = partition(
        ("F-left", "U002", left),
        ("F-right", "U002", right),
        ("F-multi", "U002", multipart),
        ("A-U002", "U002", MultiPolygon([a, b])),
    )
    audits = [approved("AR-a", a), approved("AR-b", b)]
    result = dissolve(before, audits).set_index("feature_id")
    assert result.at["F-left", "geometry"].equals(box(-1, 0, 3, 2))
    assert result.at["F-right", "geometry"].equals(box(19, 0, 23, 2))
    assert result.at["F-multi", "geometry"].equals(box(50, 0, 51, 2))
    assert [row["host_feature_id"] for row in audits] == ["F-left", "F-right"]
    assert all(json.loads(row["absorbed_ids"]) == [] for row in audits)
