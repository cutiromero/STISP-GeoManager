"""A named-band raster port for all geology kernels, with legacy compatibility."""

from contextlib import contextmanager, ExitStack
from functools import wraps
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import xml.etree.ElementTree as ET

import numpy as np
import rasterio

from multi_io import RASTERS, digest, raster_band_identity
from multi_windows import windows

MAX_CLASSES = 64
SUFFIXES = {"before", "hits", "groups", "corrected", "weight", "changes"}
TYPES = {
    "uint8": "Byte",
    "uint16": "UInt16",
    "uint32": "UInt32",
    "int16": "Int16",
    "int32": "Int32",
    "float32": "Float32",
    "float64": "Float64",
}


def _vrt(path, source, band, target):
    root = ET.Element(
        "VRTDataset", rasterXSize=str(source.width), rasterYSize=str(source.height)
    )
    ET.SubElement(root, "SRS").text = source.crs.to_wkt()
    ET.SubElement(root, "GeoTransform").text = ",".join(
        map(str, source.transform.to_gdal())
    )
    raster = ET.SubElement(
        root, "VRTRasterBand", dataType=TYPES[source.dtypes[band - 1]], band="1"
    )
    if source.nodata is not None:
        ET.SubElement(raster, "NoDataValue").text = str(source.nodata)
    simple = ET.SubElement(raster, "SimpleSource")
    ET.SubElement(simple, "SourceFilename", relativeToVRT="0").text = str(
        Path(path).resolve()
    )
    ET.SubElement(simple, "SourceBand").text = str(band)
    for tag in ["SrcRect", "DstRect"]:
        ET.SubElement(
            simple,
            tag,
            xOff="0",
            yOff="0",
            xSize=str(source.width),
            ySize=str(source.height),
        )
    ET.ElementTree(root).write(target, encoding="utf-8", xml_declaration=True)


class StackContext:
    def __init__(
        self, context, directory, source, path, labels, weight, weight_path, stage
    ):
        self.original, self.directory, self.source, self.labels = (
            context,
            Path(directory),
            source,
            labels,
        )
        self.inputs = {}
        self.products = {}
        self.proofs = {}
        self.suffixes = {
            "check": {"before", "hits", "groups"},
            "apply": {"corrected", "weight", "changes"},
        }.get(stage, set())
        for index, (key, label) in enumerate(labels.items(), 1):
            target = self.directory / (key + ".vrt")
            _vrt(path, source, index, target)
            self.inputs[key] = target
            if weight is not None:
                target = self.directory / (key + "_weight.vrt")
                _vrt(weight_path, weight, index, target)
                self.inputs[key + "_weight"] = target

    def __getattr__(self, name):
        return getattr(self.original, name)

    def input_path(self, key):
        if key in self.inputs:
            return self.inputs[key]
        return self.original.input_path(key)

    def input_evidence(self, key):
        if key not in self.inputs:
            return (
                self.original.input_evidence(key)
                if hasattr(self.original, "input_evidence")
                else None
            )
        if key not in self.proofs:
            identity = raster_band_identity(self.inputs[key])
            self.proofs[key] = {
                "raster": identity,
                "sha256": digest({"domain": "raster-band-v1", "identity": identity}),
            }
        return self.proofs[key]

    def output_path(self, name):
        for key in self.labels:
            for suffix in SUFFIXES:
                if name == f"{key}_{suffix}.tif":
                    path = self.directory / name
                    self.products.setdefault(suffix, {})[key] = path
                    return path
        return self.original.output_path(name)

    def merge(self):
        # Only kernels that published per-class rasters need an exchange stack.
        suffixes = self.suffixes
        for suffix in sorted(suffixes):
            products = self.products.get(suffix, {})
            if self.labels and set(products) != set(self.labels):
                raise ValueError("类别输出不完整，未发布派生栅格集")
            dtype = (
                "float32"
                if suffix == "weight"
                else "uint32"
                if suffix == "groups"
                else "uint8"
            )
            names = list(self.labels.values()) or ["未提供类别资料"]
            profile = {
                **self.source.profile,
                "driver": "GTiff",
                "count": len(names),
                "dtype": dtype,
                "nodata": 255 if suffix in {"before", "corrected", "weight"} else None,
                "compress": "DEFLATE",
            }
            target = self.original.output_path("alteration_stack_" + suffix + ".tif")
            with rasterio.open(target, "w", **profile) as dst:
                for index, name in enumerate(names, 1):
                    dst.set_band_description(index, name)
                for index, key in enumerate(self.labels or {"empty": ""}, 1):
                    with ExitStack() as stack:
                        product = (
                            stack.enter_context(rasterio.open(products[key]))
                            if key in products
                            else None
                        )
                        if product and (
                            product.crs != self.source.crs
                            or product.transform != self.source.transform
                            or product.shape != self.source.shape
                        ):
                            raise ValueError("修正输出的类别网格发生变化")
                        for window in windows(profile):
                            values = (
                                product.read(1, window=window)
                                if product
                                else np.zeros(
                                    (int(window.height), int(window.width)), dtype=dtype
                                )
                            )
                            if suffix in {"before", "corrected", "weight"}:
                                valid = self.source.read_masks(index, window=window) > 0
                                values = np.where(valid, values, 255)
                            dst.write(values.astype(dtype), index, window=window)
                dst.update_tags(
                    stisp_input_semantics="class_mask_stack_v1",
                    stisp_empty_collection="0" if self.labels else "1",
                )


def _has_input(context, key):
    try:
        return bool(context.input_path(key))
    except KeyError:
        return False


@contextmanager
def normalized(context, stage):
    if not _has_input(context, "alteration_stack"):
        yield context
        return
    previous = dict(RASTERS)
    with ExitStack() as stack:
        path = context.input_path("alteration_stack")
        source = stack.enter_context(rasterio.open(path))
        if source.crs is None or not 1 <= source.count <= MAX_CLASSES:
            raise ValueError("类别栅格集缺少坐标系或超出资源边界")
        labels = {}
        if source.tags().get("stisp_empty_collection") != "1":
            for index, name in enumerate(source.descriptions, 1):
                if not name or len(name) > 160 or name in labels.values():
                    raise ValueError("类别栅格集须保留唯一、真实的类别名称")
                label = name + "化" if name + "化" in previous.values() else name
                key = next(
                    (key for key, value in previous.items() if value == label),
                    "class_" + hashlib.sha256(label.encode()).hexdigest()[:16],
                )
                if key in labels:
                    raise ValueError("同义类别应在输入准备阶段合并")
                labels[key] = label
        weight_path = (
            context.input_path("alteration_stack_weight")
            if _has_input(context, "alteration_stack_weight")
            else None
        )
        weight = (
            stack.enter_context(rasterio.open(weight_path)) if weight_path else None
        )
        if weight and (
            weight.count != source.count
            or weight.shape != source.shape
            or weight.transform != source.transform
            or weight.crs != source.crs
            or weight.descriptions != source.descriptions
        ):
            raise ValueError("类别权重栅格集与类别标签或网格不一致")
        temporary = stack.enter_context(
            TemporaryDirectory(
                prefix=".class-port-",
                dir=Path(context.output_path("quality.json")).parent,
            )
        )
        wrapped = StackContext(
            context, temporary, source, path, labels, weight, weight_path, stage
        )
        wrapped._class_mask_labels = list(labels.items())
        try:
            RASTERS.clear()
            RASTERS.update(labels)
            yield wrapped
            wrapped.merge()
        finally:
            RASTERS.clear()
            RASTERS.update(previous)


def raster_inputs(stage):
    def decorate(function):
        @wraps(function)
        def run(context):
            with normalized(context, stage) as prepared:
                return function(prepared)

        return run

    return decorate
