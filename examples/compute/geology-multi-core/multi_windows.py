"""Bounded raster windows and disk-backed, exact eight-connected components."""

import sqlite3
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window
from scipy import ndimage

WINDOW_SIZE = 512
FULL_RASTER_PIXELS = 262144
GDAL_CACHE_MB = 16
SQLITE_CACHE_KIB = 2048


def windows(profile):
    height, width = profile["height"], profile["width"]
    size = max(height, width) if height * width <= FULL_RASTER_PIXELS else WINDOW_SIZE
    for row in range(0, height, size):
        for column in range(0, width, size):
            yield Window(
                column, row, min(size, width - column), min(size, height - row)
            )


def ordered_windows(source):
    rows = max(1, FULL_RASTER_PIXELS // source.width)
    for row in range(0, source.height, rows):
        for column in range(0, source.width, FULL_RASTER_PIXELS):
            yield Window(
                column,
                row,
                min(FULL_RASTER_PIXELS, source.width - column),
                min(rows, source.height - row),
            )


def create(path, profile, dtype, count=1):
    return rasterio.open(
        path,
        "w+",
        driver="GTiff",
        width=profile["width"],
        height=profile["height"],
        count=count,
        dtype=dtype,
        crs=profile["crs"],
        transform=profile["transform"],
        tiled=True,
        blockxsize=256,
        blockysize=256,
        compress="DEFLATE",
        BIGTIFF="IF_SAFER",
    )


class Components:
    def __init__(self, path, source, predicate):
        self.path = Path(path)
        self.database = sqlite3.connect(str(self.path) + ".sqlite")
        self.database.execute(f"PRAGMA cache_size=-{SQLITE_CACHE_KIB}")
        self.database.execute("PRAGMA temp_store=FILE")
        self.database.execute(
            "CREATE TABLE parts (id INTEGER PRIMARY KEY, parent INTEGER, pixels INTEGER, "
            "r0 INTEGER, c0 INTEGER, r1 INTEGER, c1 INTEGER, first INTEGER)"
        )
        self.profile = source.profile.copy()
        self.labels = create(self.path, self.profile, "uint32")
        offset = 0
        for window in windows(self.profile):
            mask = predicate(window)
            labels, count = ndimage.label(
                mask, structure=np.ones((3, 3), dtype="uint8")
            )
            if offset + count > np.iinfo(np.uint32).max:
                raise ValueError("栅格连通分量超过uint32上限，请缩小研究范围")
            identities, positions, sizes = np.unique(
                labels, return_index=True, return_counts=True
            )
            counts = dict(zip(identities.tolist(), sizes.tolist()))
            first = dict(zip(identities.tolist(), positions.tolist()))
            objects = ndimage.find_objects(labels)
            row, column = int(window.row_off), int(window.col_off)
            self.database.executemany(
                "INSERT INTO parts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    (
                        offset + identity,
                        offset + identity,
                        counts[identity],
                        row + slices[0].start,
                        column + slices[1].start,
                        row + slices[0].stop,
                        column + slices[1].stop,
                        (row + int(first[identity]) // labels.shape[1])
                        * self.profile["width"]
                        + column
                        + int(first[identity]) % labels.shape[1],
                    )
                    for identity, slices in enumerate(objects, 1)
                ),
            )
            labels = labels.astype("uint32")
            np.add(labels, offset, out=labels, where=labels > 0)
            self._join_edges(labels, window)
            self.labels.write(labels, 1, window=window)
            offset += count
        self.database.commit()

    def root(self, identity):
        while True:
            parent = self.database.execute(
                "SELECT parent FROM parts WHERE id=?", (identity,)
            ).fetchone()[0]
            if parent == identity:
                return identity
            grandparent = self.database.execute(
                "SELECT parent FROM parts WHERE id=?", (parent,)
            ).fetchone()[0]
            self.database.execute(
                "UPDATE parts SET parent=? WHERE id=?", (grandparent, identity)
            )
            identity = parent

    def _join(self, first, second):
        if not first or not second or first == second:
            return
        first, second = self.root(int(first)), self.root(int(second))
        if first == second:
            return
        first, second = min(first, second), max(first, second)
        self.database.execute(
            "UPDATE parts SET pixels=pixels+(SELECT pixels FROM parts WHERE id=?), "
            "r0=min(r0,(SELECT r0 FROM parts WHERE id=?)), "
            "c0=min(c0,(SELECT c0 FROM parts WHERE id=?)), "
            "r1=max(r1,(SELECT r1 FROM parts WHERE id=?)), "
            "c1=max(c1,(SELECT c1 FROM parts WHERE id=?)), "
            "first=min(first,(SELECT first FROM parts WHERE id=?)) WHERE id=?",
            (second,) * 6 + (first,),
        )
        self.database.execute("UPDATE parts SET parent=? WHERE id=?", (first, second))

    def _pairs(self, first, second):
        pairs = np.column_stack((first.ravel(), second.ravel()))
        pairs = pairs[(pairs > 0).all(axis=1)]
        for left, right in np.unique(pairs, axis=0):
            self._join(left, right)

    def _join_edges(self, labels, window):
        row, column = int(window.row_off), int(window.col_off)
        height, width = labels.shape
        if row:
            for delta in (-1, 0, 1):
                start = max(0, column + delta)
                stop = min(self.profile["width"], column + width + delta)
                above = self.labels.read(
                    1, window=Window(start, row - 1, stop - start, 1)
                )
                self._pairs(
                    labels[0, start - column - delta : stop - column - delta], above
                )
        if column:
            for delta in (-1, 0, 1):
                start, stop = (
                    max(row, row + delta),
                    min(row + height, row + height + delta),
                )
                left = self.labels.read(
                    1, window=Window(column - 1, start, 1, stop - start)
                )
                self._pairs(labels[start - row - delta : stop - row - delta, 0], left)

    def small(self, window, threshold):
        labels = self.labels.read(1, window=window)
        identities, inverse = np.unique(labels, return_inverse=True)
        selected = np.zeros(len(identities), dtype=bool)
        for index, identity in enumerate(identities):
            if identity:
                selected[index] = (
                    self.database.execute(
                        "SELECT pixels FROM parts WHERE id=?",
                        (self.root(int(identity)),),
                    ).fetchone()[0]
                    < threshold
                )
        return selected[inverse].reshape(labels.shape)

    def summary(self):
        count, pixels, row0, column0, row1, column1 = self.database.execute(
            "SELECT count(*), sum(pixels), min(r0), min(c0), max(r1), max(c1) "
            "FROM parts WHERE parent=id"
        ).fetchone()
        top = self.database.execute(
            "SELECT pixels,r0,c0,r1,c1 FROM parts WHERE parent=id "
            "ORDER BY pixels DESC,first ASC LIMIT 3"
        ).fetchall()
        return count, pixels or 0, (row0, column0, row1, column1), top

    def close(self):
        self.labels.close()
        self.database.close()
        self.path.unlink(missing_ok=True)
        Path(str(self.path) + ".sqlite").unlink(missing_ok=True)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
