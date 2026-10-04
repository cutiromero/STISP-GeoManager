"""Exercise the shipped repair package in the actual isolated-process runner."""

import json
from types import SimpleNamespace

import geopandas as gpd
from shapely.geometry import Polygon

from apps.compute import runtime
from apps.compute.data import inspect_output
from apps.compute.packages import inspect_package
from apps.compute.quality import read_quality_report
from apps.compute.templates import build_package
from tests.unit.test_compute_runtime import native_config


def test_geometry_repair_runs_in_real_process_with_quality_and_audit(
    tmp_path, monkeypatch
):
    package = tmp_path / "algorithm"
    inputs = tmp_path / "inputs"
    results = tmp_path / "results"
    for directory in (package, inputs, results):
        directory.mkdir()
    archive = tmp_path / "algorithm.zip"
    archive.write_bytes(build_package(7)[0])
    manifest = inspect_package(archive, package)
    source = inputs / "features.gpkg"
    gpd.GeoDataFrame(
        {"rock": ["控制样本"]},
        geometry=[Polygon([(0, 0), (10, 10), (0, 10), (10, 0)])],
        crs=32644,
    ).to_file(source, layer="data", driver="GPKG", index=False)
    before = source.read_bytes()
    (inputs / "context.json").write_text(
        json.dumps(
            {
                "inputs": {"features": {"path": "/inputs/features.gpkg"}},
                "parameters": {"max_area_change_pct": 5},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "config", native_config)
    state = runtime.inspect_runtime()
    assert state["ready"], state
    runtime.execute(
        SimpleNamespace(runtime_digest=state["imageDigest"]),
        package,
        inputs,
        results,
        manifest,
        lambda: None,
    )
    assert source.read_bytes() == before
    quality = read_quality_report(results, manifest)
    assert quality["status"] == "needs_review"
    assert quality["metrics"]["validAfter"] == 1
    assert quality["metrics"]["needsReview"] == 1
    for output in manifest["outputs"]:
        assert inspect_output(results / output["file"], output["kind"])
    repaired = gpd.read_file(results / "repaired.gpkg")
    assert repaired.is_valid.all()
    assert repaired.area.iloc[0] == 50
