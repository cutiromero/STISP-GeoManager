import zipfile

import pytest

from apps.compute.archives import inspect_archive
from apps.compute.packages import ComputeError


def test_archive_checks_files_and_uncompressed_budget(tmp_path):
    path = tmp_path / "result.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("result.tif", b"fixture")
    assert inspect_archive(path, 100)["files"] == ["result.tif"]
    with pytest.raises(ComputeError):
        inspect_archive(path, 2)


@pytest.mark.parametrize(
    "name",
    [
        "../result.tif",
        "/result.tif",
        "folder/result.tif",
        "C:result.tif",
        "folder\\result.tif",
    ],
)
def test_archive_rejects_unsafe_names(tmp_path, name):
    path = tmp_path / "result.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(name, b"fixture")
    with pytest.raises(ComputeError):
        inspect_archive(path, 100)
