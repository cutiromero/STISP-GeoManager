"""Build four isolated, reproducible worker packages from shared text sources."""

import argparse
import io
from pathlib import Path
import zipfile

IDENTIFIERS = tuple(
    "geology-multi-" + suffix for suffix in ("check", "apply", "relations", "prospect")
)


def build(identifier):
    if identifier not in IDENTIFIERS:
        raise ValueError("Unknown geology operator")
    folder = Path(__file__).resolve().parent
    source = folder.parent / identifier
    files = {
        name: (source / name).read_bytes()
        for name in ("main.py", "operator.yaml", "README.md")
    }
    files.update(
        {path.name: path.read_bytes() for path in sorted(folder.glob("multi_*.py"))}
    )
    files.update(
        {path.name: path.read_bytes() for path in sorted(source.glob("prospect_*.py"))}
    )
    for path in sorted((source / "selftest").glob("*.json")):
        files["selftest/" + path.name] = path.read_bytes()
    files["main.py"] += (
        b"\nfrom operator_sdk import diagnosed\nrun = diagnosed()(run)\n"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            member = zipfile.ZipInfo(name, date_time=(2026, 10, 23, 0, 0, 0))
            member.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(member, data)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    arguments = parser.parse_args()
    arguments.directory.mkdir(parents=True, exist_ok=True)
    for identifier in IDENTIFIERS:
        (arguments.directory / (identifier + ".zip")).write_bytes(build(identifier))
    print("Built 4 isolated geology trial packages")


if __name__ == "__main__":
    main()
