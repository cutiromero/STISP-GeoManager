"""Stage only the immutable operator ZIP needed by a copied candidate record."""

import hashlib
import json
from pathlib import Path
import shutil
import tomllib

# CONFIGURATION
PRODUCTION_CONFIG = Path("/root/autodl-tmp/geomanager-config-0.1.6-production/app.toml")
MAX_PACKAGE_BYTES = 16 * 1024**2


def stage_published_package(source_directory, root):
    from apps.compute.models import AlgorithmVersion
    from apps.core.storage import app_path
    from apps.projects.context import selected_project_id

    settings = tomllib.loads(PRODUCTION_CONFIG.read_text())
    original = Path(settings["application"]["storage"]["app_data"]).resolve()
    manifest = json.loads((Path(source_directory) / "operator.yaml").read_text())
    for version in AlgorithmVersion.objects.filter(
        algorithm__identifier=manifest["identifier"],
        algorithm__project_tag_id=selected_project_id(),
        version=manifest["version"],
    ):
        source = original / version.package_path
        target = app_path(version.package_path)
        assert source.resolve().is_relative_to(
            original
        ) and target.resolve().is_relative_to(root)
        assert not source.is_symlink() and source.stat().st_size <= MAX_PACKAGE_BYTES
        with source.open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == version.checksum
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
