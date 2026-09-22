from __future__ import annotations


class RasterRenderError(RuntimeError):
    pass


class RasterTileOutsideExtent(RuntimeError):
    pass


class RasterImportError(RuntimeError):
    pass


class RasterJobError(RuntimeError):
    pass
