from __future__ import annotations

RASTER_EXTENSIONS = {
    ".tif",
    ".tiff",
    ".img",
    ".vrt",
    ".dat",
    ".bsq",
    ".bil",
    ".bip",
}
WEB_MERCATOR_HALF_WORLD = 20037508.342789244
DEFAULT_TILE_SIZE = 256

PALETTES: dict[str, list[str]] = {
    "poplar": ["#183f39", "#5f9360", "#e8ba5e"],
    "viridis": ["#440154", "#31688e", "#35b779", "#fde725"],
    "terrain": ["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#8c510a"],
    "thermal": ["#23344c", "#c45c46", "#f6cd70"],
}

UNIQUE_COLORS = [
    "#00000000",
    "#2f7d62",
    "#d9a441",
    "#3b79b7",
    "#c45c46",
    "#7a5aa6",
    "#5aa6a6",
    "#8c6d31",
]
