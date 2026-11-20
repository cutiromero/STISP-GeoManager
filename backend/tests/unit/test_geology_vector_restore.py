from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import runpy
from zipfile import ZipFile

import pytest


BUILDER = Path(__file__).resolve().parents[3] / (
    "examples/compute/geology-multi-core/build_vector_restore.py"
)
restore = runpy.run_path(str(BUILDER))


def package(version, main, grid, **extras):
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for name, data in {
            "operator.yaml": json.dumps(
                {
                    "identifier": "geology-multi-apply",
                    "version": version,
                    "inputs": [{"key": "lithology"}],
                }
            ),
            "main.py": main,
            "multi_grid.py": grid,
            "multi_apply.py": "whole feature vector apply",
            **extras,
        }.items():
            archive.writestr(name, data)
    return output.getvalue()


def test_restore_prior_vector_entry_without_archives_or_input_contract_regression():
    old = package("1.5.1", "checked original vector entry", "prior grid")
    current = package(
        "1.7.3",
        "pixel overlay entry",
        "optimized grid",
        **{"archive_overlay.py": "pixel overlay", "evidence/archive.npz": "payload"},
    )
    spec = restore["Restore"](
        "1.5.1",
        sha256(old).hexdigest(),
        "1.7.3",
        sha256(current).hexdigest(),
        "1.7.5",
        "原矢量要素",
    )
    built = restore["build"]("geology-multi-apply", spec, old, current)
    with ZipFile(BytesIO(built)) as archive:
        assert archive.read("main.py") == b"checked original vector entry"
        assert archive.read("multi_grid.py") == b"optimized grid"
        assert "archive_overlay.py" not in archive.namelist()
        assert not any(name.startswith("evidence/") for name in archive.namelist())
        manifest = json.loads(archive.read("operator.yaml"))
        assert manifest["version"] == "1.7.5"
        assert manifest["inputs"] == [{"key": "lithology"}]
    with pytest.raises(ValueError, match="摘要不符"):
        restore["build"]("geology-multi-apply", spec, old + b" ", current)
