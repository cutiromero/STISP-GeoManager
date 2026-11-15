"""Exact eight-connected frontier counting and lossless empty-block reuse."""

from pathlib import Path
import xml.etree.ElementTree as etree

# CONFIGURATION
MAX_EMPTY_SIGNATURES = 64
MAX_ENCODED_SIGNATURE_BYTES = 65536


class StreamingPatchCounter:
    def __init__(self, width):
        import numpy as np

        self.width = width
        self.top = np.zeros(width, dtype="int64")
        self.bottom = np.zeros(width, dtype="int64")
        self.parents = [0]
        self.row = None
        self.left = None
        self.completed = 0

    def find(self, value):
        while self.parents[value] != value:
            self.parents[value] = self.parents[self.parents[value]]
            value = self.parents[value]
        return value

    def union(self, first, second):
        if first and second:
            a, b = self.find(int(first)), self.find(int(second))
            if a != b:
                self.parents[max(a, b)] = min(a, b)

    def roll(self):
        import numpy as np

        roots = {self.find(value) for value in range(1, len(self.parents))}
        active = {self.find(int(value)) for value in np.unique(self.bottom) if value}
        self.completed += len(roots - active)
        mapping = {value: index for index, value in enumerate(sorted(active), 1)}
        old = self.bottom
        self.top = np.array(
            [mapping.get(self.find(int(value)), 0) if value else 0 for value in old],
            dtype="int64",
        )
        self.bottom = np.zeros(self.width, dtype="int64")
        self.parents = list(range(len(mapping) + 1))
        self.left = None

    def add(self, target, row, col, height, width):
        import numpy as np
        from scipy.ndimage import label

        if self.row is not None and row != self.row:
            self.roll()
        self.row = row
        if target is None or not target.any():
            self.left = np.zeros(height, dtype="int64")
            return
        labels, count = label(target, structure=np.ones((3, 3), dtype="uint8"))
        boundary = set(
            int(value)
            for value in np.unique(
                np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])
            )
            if value
        )
        self.completed += count - len(boundary)
        identifiers = np.zeros(count + 1, dtype="int64")
        for value in boundary:
            identifiers[value] = len(self.parents)
            self.parents.append(len(self.parents))
        top_values = identifiers[labels[0]]
        for offset, current in enumerate(top_values):
            if current:
                for neighbor in range(
                    max(0, col + offset - 1), min(self.width, col + offset + 2)
                ):
                    self.union(current, self.top[neighbor])
        if self.left is not None:
            for offset, current in enumerate(identifiers[labels[:, 0]]):
                if current:
                    for neighbor in range(max(0, offset - 1), min(height, offset + 2)):
                        self.union(current, self.left[neighbor])
        self.bottom[col : col + width] = identifiers[labels[-1]]
        self.left = identifiers[labels[:, -1]]

    def finish(self):
        if self.row is not None:
            self.roll()
        return self.completed + len(self.parents) - 1


class InvalidTileCache:
    """Reuse only encoded blocks whose intrinsic values were proven invalid."""

    def __init__(self, path):
        from osgeo import gdal

        self.empty = set()
        self.offset = (0, 0)
        self.dataset = gdal.Open(str(path))
        if self.dataset.GetDriver().ShortName == "VRT":
            tree = etree.parse(path)
            filename = tree.find(".//SourceFilename")
            rectangle = tree.find(".//SrcRect")
            if filename is not None:
                source = Path(filename.text)
                if filename.get("relativeToVRT") == "1":
                    source = Path(path).parent / source
                self.dataset = gdal.Open(str(source))
                if rectangle is not None:
                    self.offset = (
                        int(rectangle.get("xOff")),
                        int(rectangle.get("yOff")),
                    )
                path = source
        self.file = (
            Path(path).open("rb")
            if self.dataset.GetDriver().ShortName == "GTiff"
            else None
        )
        self.block = self.dataset.GetRasterBand(1).GetBlockSize()
        self.pixel = (
            self.dataset.GetMetadata("IMAGE_STRUCTURE").get("INTERLEAVE") == "PIXEL"
        )

    def signature(self, row, col, height, width):
        if self.file is None:
            return None
        x, y = col + self.offset[0], row + self.offset[1]
        bx, by = self.block
        encoded = []
        total = 0
        bands = [1] if self.pixel else range(1, self.dataset.RasterCount + 1)
        for band in bands:
            source = self.dataset.GetRasterBand(band)
            for line in range(y // by, (y + height - 1) // by + 1):
                for column in range(x // bx, (x + width - 1) // bx + 1):
                    offset = source.GetMetadataItem(
                        f"BLOCK_OFFSET_{column}_{line}", "TIFF"
                    )
                    size = source.GetMetadataItem(f"BLOCK_SIZE_{column}_{line}", "TIFF")
                    if offset is None or size is None:
                        return None
                    length = int(size)
                    total += length
                    if total > MAX_ENCODED_SIGNATURE_BYTES:
                        return None
                    self.file.seek(int(offset))
                    data = self.file.read(length)
                    if len(data) != length:
                        raise ValueError("原始压缩块不完整")
                    encoded.append(data)
        return (height, width, x % bx, y % by, *encoded)

    def remember(self, signature, block, nodata):
        import numpy as np

        if signature is None or len(self.empty) >= MAX_EMPTY_SIGNATURES:
            return
        data = np.ma.getdata(block)
        valid = np.isfinite(data).all(axis=0)
        for band, value in enumerate(nodata):
            if value is not None and np.isfinite(value):
                valid &= data[band] != value
        if not valid.any():
            self.empty.add(signature)

    def close(self):
        if self.file is not None:
            self.file.close()
        self.dataset = None
