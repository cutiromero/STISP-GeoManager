import io
from pathlib import Path
import zipfile
from django.conf import settings
from .packages import ComputeError

TEMPLATES = {
    1: "raster-linear",
    2: "vector-buffer",
    3: "table-group-summary",
    4: "raster-ndvi",
}


def build_package(template_id):
    name = TEMPLATES.get(template_id)
    if not name:
        raise ComputeError("模板不存在", 404)
    directory = Path(settings.PROGRAM_ROOT) / "examples" / "compute" / name
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.name in {
                "main.py",
                "operator.yaml",
                "README.md",
            }:
                archive.writestr(path.name, path.read_bytes())
    return stream.getvalue(), name
