"""Run each real operator in fresh processes; enforce address space on Linux."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import pytest

MINERAL_COUNTS = (5, 10)
RASTER_SIZE = 2000
ADDRESS_SPACE_MB = 1024
MAX_PEAK_GROWTH_MB = 32
ENFORCE_ADDRESS_SPACE = sys.platform == "linux"
WORK_DIRECTORY = None
STAGES = ("check", "apply", "prospect")
ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / "examples/compute/geology-multi-core"


def minerals(count):
    sys.path.insert(0, str(CORE))
    from multi_io import RASTERS

    original = {key: value for key, value in list(RASTERS.items())[:5]}
    RASTERS.clear()
    RASTERS.update(original)
    RASTERS.update(
        {f"synthetic_{index}": f"合成矿物{index}" for index in range(6, count + 1)}
    )
    return RASTERS


def prepare(directory, count):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from tests.unit.test_geology_multi_algorithms import (
        Context,
        X,
        Y,
        approval_context,
        fixture,
        load,
        raster_inputs,
        read,
        write,
    )
    from multi_windows import create, windows

    directory.mkdir(parents=True)
    initial, _ = fixture(directory)
    names = minerals(count)
    profile = {
        "width": RASTER_SIZE,
        "height": RASTER_SIZE,
        "crs": rasterio.crs.CRS.from_epsg(32646),
        "transform": from_origin(X, Y + 1000, 1000 / RASTER_SIZE, 1000 / RASTER_SIZE),
    }
    for index, key in enumerate(names):
        path = directory / (key + ".tif")
        with create(path, profile, "uint8") as target:
            for window in windows(profile):
                rows = np.arange(
                    int(window.row_off), int(window.row_off + window.height)
                )[:, None]
                columns = np.arange(
                    int(window.col_off), int(window.col_off + window.width)
                )[None, :]
                values = ((rows // 37 + columns // 43 + index) % 11 == 0).astype(
                    "uint8"
                )
                target.write(values, 1, window=window)
        initial.inputs[key] = path
    rows = read(initial.inputs["rules"])
    for row in rows:
        if row["rule_id"] == "P-02":
            params = json.loads(row["params_json"])
            params.update(alteration_types=list(names.values()), min_types=0.2)
            row["params_json"] = json.dumps(params)
    write(initial.inputs["rules"], rows)
    load("check")(initial)
    findings = read(initial.output_path("issues.csv"))
    edited = approval_context(
        directory, initial, [row for row in findings if row["element"] == "alteration"]
    )
    load("apply")(edited)
    relations = Context(
        directory / "relations",
        {**initial.inputs, "faults": edited.output_path("faults.gpkg")},
        initial.parameters,
    )
    load("relations")(relations)
    prospect = Context(
        directory / "prospect",
        {
            **initial.inputs,
            "before_lithology": initial.inputs["lithology"],
            "before_faults": initial.inputs["faults"],
            "lithology": edited.output_path("lithology.gpkg"),
            "faults": edited.output_path("faults.gpkg"),
            **raster_inputs(initial, edited),
            **{"before_" + key: initial.inputs[key] for key in names},
            **{key: edited.output_path(key + "_corrected.tif") for key in names},
            **{
                key + "_weight": edited.output_path(key + "_weight.tif")
                for key in names
            },
            "intersections": relations.output_path("intersections.gpkg"),
        },
        initial.parameters,
    )
    contexts = {"check": initial, "apply": edited, "prospect": prospect}
    (directory / "contexts.json").write_text(
        json.dumps(
            {
                stage: {
                    "inputs": {key: str(path) for key, path in context.inputs.items()},
                    "parameters": context.parameters,
                    "directory": str(context.directory),
                }
                for stage, context in contexts.items()
            }
        )
    )


def worker(directory, count, stage):
    import resource

    from tests.unit.test_geology_multi_algorithms import Context, load

    minerals(count)
    context = json.loads((directory / "contexts.json").read_text())[stage]
    load(stage)(
        Context(
            Path(context["directory"]),
            {key: Path(path) for key, path in context["inputs"].items()},
            context["parameters"],
        )
    )
    usage = resource.getrusage(resource.RUSAGE_SELF)
    peak_mb = usage.ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024)
    virtual_mb = None
    if sys.platform == "linux":
        line = next(
            line
            for line in Path("/proc/self/status").read_text().splitlines()
            if line.startswith("VmPeak:")
        )
        virtual_mb = int(line.split()[1]) / 1024
    limit = resource.getrlimit(resource.RLIMIT_AS)[0]
    print(
        json.dumps(
            {
                "stage": stage,
                "minerals": count,
                "size": RASTER_SIZE,
                "peak_rss_mb": round(peak_mb, 2),
                "peak_virtual_mb": virtual_mb,
                "address_space_limit_mb": limit / 1024**2
                if limit != resource.RLIM_INFINITY
                else None,
            }
        )
    )


def measure(directory, enforce):
    from multi_io import RASTERS

    original = RASTERS.copy()
    results = []
    try:
        for count in MINERAL_COUNTS:
            case = directory / str(count)
            prepare(case, count)
            for stage in STAGES:
                environment = {
                    **os.environ,
                    "OPENBLAS_NUM_THREADS": "1",
                    "OMP_NUM_THREADS": "1",
                    "PYTHONPATH": str(ROOT / "backend"),
                    "DJANGO_SETTINGS_MODULE": "geomanager.test_settings",
                }
                code = (
                    "import django; django.setup(); from pathlib import Path; "
                    "from tests.unit.test_raster_memory import worker; "
                    f"worker(Path({str(case)!r}), {count}, {stage!r})"
                )
                if enforce:
                    memory = ADDRESS_SPACE_MB * 1024**2
                    code = (
                        f"import resource; resource.setrlimit(resource.RLIMIT_AS, ({memory}, {memory})); "
                        + code
                    )

                result = subprocess.run(
                    [sys.executable, "-c", code],
                    env=environment,
                    cwd=ROOT / "backend",
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
                assert result.returncode == 0, (
                    f"{count} minerals / {stage}: {result.stderr}"
                )
                measured = json.loads(result.stdout.splitlines()[-1])
                if enforce:
                    assert measured["address_space_limit_mb"] == ADDRESS_SPACE_MB
                    assert measured["peak_virtual_mb"] <= ADDRESS_SPACE_MB
                results.append(measured)
    finally:
        RASTERS.clear()
        RASTERS.update(original)
    for stage in STAGES:
        five, ten = [row for row in results if row["stage"] == stage]
        assert ten["peak_rss_mb"] <= five["peak_rss_mb"] + MAX_PEAK_GROWTH_MB, results
        if enforce:
            assert (
                ten["peak_virtual_mb"] <= five["peak_virtual_mb"] + MAX_PEAK_GROWTH_MB
            ), results
    return {"limit_enforced": enforce, "measurements": results}


@pytest.mark.skipif(
    not ENFORCE_ADDRESS_SPACE,
    reason="RLIMIT_AS enforcement requires Linux; macOS rejects this limit",
)
def test_each_operator_under_one_gib_and_constant_mineral_memory(tmp_path):
    sys.path.insert(0, str(CORE))
    results = measure(tmp_path, True)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.path[:0] = [str(ROOT / "backend"), str(CORE)]
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geomanager.test_settings")
    import django

    django.setup()
    with TemporaryDirectory(dir=WORK_DIRECTORY, prefix="raster-memory-") as directory:
        print(
            json.dumps(
                measure(Path(directory), ENFORCE_ADDRESS_SPACE),
                ensure_ascii=False,
                indent=2,
            )
        )
