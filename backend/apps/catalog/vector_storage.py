from __future__ import annotations

import threading
from pathlib import Path


GEOPACKAGE_WRITE_LOCK = threading.RLock()


def append_geopackage_layer(path: Path, layer_name: str, frame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with GEOPACKAGE_WRITE_LOCK:
        if path.exists():
            frame.to_file(path, layer=layer_name, driver="GPKG", mode="a")
        else:
            frame.to_file(path, layer=layer_name, driver="GPKG")
