"""Build one reproducible candidate package without data or runtime configuration."""

from pathlib import Path
import io
import zipfile

# ==================== CONFIGURATION ====================
SOURCE = Path(__file__).resolve().parent
CORE = SOURCE.parent / "geology-multi-core"
OUTPUT = (
    SOURCE.parents[2]
    / ".runtime/prospect-region-candidate/geology-prospect-regions-candidate.zip"
)
# =======================================================


def build():
    names = [
        "main.py",
        "region_fields.py",
        "region_zones.py",
        "region_boundaries.py",
        "operator.yaml",
        "README.md",
    ]
    files = {name: (SOURCE / name).read_bytes() for name in names}
    files.update(
        {path.name: path.read_bytes() for path in sorted(CORE.glob("multi_*.py"))}
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            member = zipfile.ZipInfo(name, date_time=(2026, 11, 7, 0, 0, 0))
            member.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(member, data)
    return output.getvalue()


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(build())
    print(OUTPUT)
