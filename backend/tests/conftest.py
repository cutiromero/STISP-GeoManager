import os
from pathlib import Path

import pytest


os.environ.setdefault("HUYANG_DISABLE_RASTER_STARTUP_SCAN", "1")


def pytest_collection_modifyitems(items):
    for item in items:
        path = Path(str(item.path))
        path_parts = set(path.parts)
        if "integration" in path_parts:
            item.add_marker(pytest.mark.integration)
            item.add_marker(pytest.mark.django_db)
        elif "unit" in path_parts:
            item.add_marker(pytest.mark.unit)
