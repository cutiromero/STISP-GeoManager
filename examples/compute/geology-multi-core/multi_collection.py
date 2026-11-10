"""同网格单波段集合到既有类别栅格集的无重采样端口桥接。"""

from functools import wraps
from pathlib import Path
from tempfile import TemporaryDirectory
import xml.etree.ElementTree as ET

import rasterio

from multi_io import RASTERS
from multi_stack import TYPES
from rasterio.enums import MaskFlags

MAX_COLLECTION_ITEMS = 64


class CollectionContext:
    def __init__(self, original, path=None, aliases=None):
        self.original, self.path, self.aliases = original, path, aliases or {}

    def __getattr__(self, name):
        return getattr(self.original, name)

    def input_path(self, key):
        if key in self.aliases:
            return self.original.input_path(self.aliases[key])
        return (
            self.path
            if key == "alteration_stack" and self.path
            else self.original.input_path(key)
        )

    def input_evidence(self, key):
        actual = self.aliases.get(key, key)
        return (
            self.original.input_evidence(actual)
            if hasattr(self.original, "input_evidence")
            else None
        )


def collection_inputs(run):
    @wraps(run)
    def wrapped(context):
        if not getattr(context, "input_collections", {}).get("minerals"):
            return run(context)
        from operator_sdk import fail, repeated_inputs

        members = repeated_inputs(context, "minerals")
        if not members:
            return run(context)
        if len(members) > MAX_COLLECTION_ITEMS:
            fail(
                context,
                "COLLECTION_CONFLICT",
                "矿物集合最多64项",
                remedy="replace_data",
                inputs=["minerals"],
            )
        for key in [
            *RASTERS,
            *(key + "_weight" for key in RASTERS),
            "alteration_stack",
            "alteration_stack_weight",
        ]:
            try:
                present = context.input_path(key)
            except KeyError:
                continue
            if present:
                fail(
                    context,
                    "COLLECTION_CONFLICT",
                    "minerals不可与旧矿物端口或类别栅格集同时绑定",
                    remedy="replace_data",
                    inputs=["minerals"],
                )
        aliases = {}
        for member in members:
            label = member["label"]
            key = next(
                (
                    key
                    for key, name in RASTERS.items()
                    if label in {name, name.removesuffix("化")}
                ),
                None,
            )
            if key:
                aliases[key] = member["key"]
        if len(members) == len(aliases) == len(RASTERS):
            return run(CollectionContext(context, aliases=aliases))
        with TemporaryDirectory(prefix="mineral-collection-") as directory:
            root, reference = None, None
            for index, member in enumerate(members, 1):
                with rasterio.open(member["path"]) as source:
                    grid = (
                        source.width,
                        source.height,
                        source.crs,
                        source.transform,
                        source.dtypes[0],
                        source.nodata,
                    )
                    if (
                        source.count != 1
                        or source.crs is None
                        or source.dtypes[0] not in TYPES
                        or any(
                            flag not in {MaskFlags.nodata, MaskFlags.all_valid}
                            for flag in source.mask_flag_enums[0]
                        )
                        or reference is not None
                        and grid != reference
                    ):
                        fail(
                            context,
                            "COLLECTION_GRID",
                            "集合须为同坐标系、同网格、同类型与NoData的单波段栅格，不能携带额外掩膜；先通过已登记适配器整理",
                            remedy="convert_input",
                            inputs=["minerals"],
                        )
                    if reference is None:
                        reference = grid
                        root = ET.Element(
                            "VRTDataset",
                            rasterXSize=str(source.width),
                            rasterYSize=str(source.height),
                        )
                        ET.SubElement(root, "SRS").text = source.crs.to_wkt()
                        ET.SubElement(root, "GeoTransform").text = ",".join(
                            map(str, source.transform.to_gdal())
                        )
                    band = ET.SubElement(
                        root,
                        "VRTRasterBand",
                        dataType=TYPES[source.dtypes[0]],
                        band=str(index),
                    )
                    ET.SubElement(band, "Description").text = member["label"]
                    if source.nodata is not None:
                        ET.SubElement(band, "NoDataValue").text = str(source.nodata)
                    simple = ET.SubElement(band, "SimpleSource")
                    ET.SubElement(
                        simple, "SourceFilename", relativeToVRT="0"
                    ).text = str(Path(member["path"]).resolve())
                    ET.SubElement(simple, "SourceBand").text = "1"
                    ET.SubElement(simple, "UseMaskBand").text = "true"
                    for tag in ("SrcRect", "DstRect"):
                        ET.SubElement(
                            simple,
                            tag,
                            xOff="0",
                            yOff="0",
                            xSize=str(source.width),
                            ySize=str(source.height),
                        )
            path = Path(directory) / "collection.vrt"
            ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
            return run(CollectionContext(context, path))

    return wrapped
