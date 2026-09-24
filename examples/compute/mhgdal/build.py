"""Build reproducible first-party MHGDAL packages from text sources."""

import io
import json
from pathlib import Path
import zipfile
from catalog import TOOLS


def build(tool):
    folder = Path(__file__).resolve().parent
    dispatch = """from raster_ops import polygonize, rasterize, raster_operation, contour
from vector_ops import vector_operation
from special_ops import sam, batch_subset, core_unroll

def run(context):
    operation = OPERATION
    if operation in {"polygonize", "footprint"}: polygonize(context, operation == "footprint")
    elif operation == "rasterize": rasterize(context)
    elif operation == "contour": contour(context)
    elif operation in {"sam", "plastics"}: sam(context)
    elif operation == "batch-subset": batch_subset(context)
    elif operation == "core-unroll": core_unroll(context)
    elif operation in {"simplify", "polygon-line", "small-polygons", "line-polygon", "vector-subset", "topology", "buffer"}: vector_operation(context, operation)
    else: raster_operation(context, operation)
""".replace("OPERATION", repr(tool["key"]))
    files = {
        name: (folder / name).read_bytes()
        for name in ["raster_ops.py", "vector_ops.py", "special_ops.py"]
    }
    files.update(
        {
            "main.py": dispatch.encode(),
            "operator.yaml": json.dumps(
                tool["manifest"], ensure_ascii=False, indent=2
            ).encode(),
            "README.md": (
                tool["manifest"]["name"]
                + "\n\n来源接口："
                + tool["source"]
                + "\n\n"
                + tool["manifest"]["description"]
                + "\n\n"
                + (folder / "README.md").read_text(encoding="utf-8")
            ).encode(),
        }
    )
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(files.items()):
            entry = zipfile.ZipInfo(name, date_time=(2026, 9, 24, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(entry, data)
    return stream.getvalue()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    for tool in TOOLS:
        (args.directory / (tool["manifest"]["identifier"] + ".zip")).write_bytes(
            build(tool)
        )
    print(f"Built {len(TOOLS)} packages")
