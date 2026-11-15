"""Prepare bounded display overviews by warping the source directly at target scale."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import xml.etree.ElementTree as etree

# CONFIGURATION
JOB_FILE = Path("/root/autodl-tmp/monitoring_previews/overview-jobs.json")
CACHE_MIB = 256
THREADS = 4
FIRST_LEVEL = 32
FURTHER_LEVELS = [2, 4, 16, 64]


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(job):
    from osgeo import gdal

    gdal.UseExceptions()
    gdal.SetCacheMax(CACHE_MIB * 1024**2)
    source = Path(job["path"]).resolve()
    processed_root = Path(job["preprocessedRoot"]).resolve()
    assert source.suffix == ".vrt" and source.is_relative_to(processed_root)
    tree = etree.parse(source)
    entry = tree.find(".//GDALWarpOptions/SourceDataset")
    assert entry is not None
    native = Path(entry.text)
    if entry.get("relativeToVRT") == "1":
        native = source.parent / native
    native = native.resolve()
    research_raster = processed_root.parent
    assert native.is_relative_to(research_raster / "original") and native.is_file()
    source_sha = sha(source)
    dataset = gdal.Open(str(source))
    size = [dataset.RasterXSize, dataset.RasterYSize]
    transform = dataset.GetGeoTransform()
    bounds = [
        transform[0],
        transform[3] + size[1] * transform[5],
        transform[0] + size[0] * transform[1],
        transform[3],
    ]
    projection = dataset.GetProjection()
    bands = dataset.RasterCount
    target = source.with_name(source.stem + ".display.vrt")
    lowres = source.with_name(source.stem + ".display-overview.tif")
    # A real small output grid avoids constructing full-resolution warped blocks.
    with tempfile.TemporaryDirectory(
        prefix=".source-overviews-", dir=source.parent
    ) as directory:
        stage = Path(directory) / "overview.tif"
        last = [-1]

        def progress(ratio, message, unused):
            percent = int(ratio * 100)
            if percent // 5 != last[0]:
                last[0] = percent // 5
                print(
                    json.dumps({"datasetId": job["datasetId"], "progress": percent}),
                    flush=True,
                )
            return 1

        overview = gdal.Warp(
            str(stage),
            str(native),
            format="GTiff",
            dstSRS=projection,
            outputBounds=bounds,
            width=(size[0] + FIRST_LEVEL - 1) // FIRST_LEVEL,
            height=(size[1] + FIRST_LEVEL - 1) // FIRST_LEVEL,
            resampleAlg="near",
            warpMemoryLimit=CACHE_MIB * 1024**2,
            warpOptions=["NUM_THREADS=" + str(THREADS), "OPTIMIZE_SIZE=YES"],
            creationOptions=[
                "TILED=YES",
                "COMPRESS=LZW",
                "PREDICTOR=3",
                "BIGTIFF=IF_SAFER",
                "SPARSE_OK=YES",
                "NUM_THREADS=" + str(THREADS),
            ],
            callback=progress,
        )
        assert overview is not None and overview.RasterCount == bands
        overview.BuildOverviews("NEAREST", FURTHER_LEVELS)
        overview.FlushCache()
        overview = None
        descriptor = Path(directory) / "display.vrt"
        with gdal.BuildVRT(str(descriptor), [str(source)]) as clone:
            clone.FlushCache()
        wrapped = etree.parse(descriptor)
        root = wrapped.getroot()
        for element in root.iter("SourceFilename"):
            if element.get("relativeToVRT") == "1":
                element.text = str((descriptor.parent / element.text).resolve())
                element.set("relativeToVRT", "0")
        for position, band in enumerate(root.findall("VRTRasterBand"), 1):
            external = etree.SubElement(band, "Overview")
            etree.SubElement(external, "SourceFilename", relativeToVRT="0").text = str(
                lowres
            )
            etree.SubElement(external, "SourceBand").text = str(position)
        assert sha(source) == source_sha
        os.replace(stage, lowres)
        wrapped.write(descriptor, encoding="UTF-8")
        os.replace(descriptor, target)
    ready = gdal.Open(str(target))
    assert ready.GetRasterBand(1).GetOverviewCount() >= 1
    # Verify full-resolution pixels and masks against the original display VRT.
    for x, y in [(0, 0), (size[0] // 2, size[1] // 2), (size[0] - 16, size[1] - 16)]:
        for band in [1, min(4, bands), bands]:
            left, right = dataset.GetRasterBand(band), ready.GetRasterBand(band)
            assert left.ReadRaster(x, y, 16, 16) == right.ReadRaster(x, y, 16, 16)
            assert left.GetMaskBand().ReadRaster(
                x, y, 16, 16
            ) == right.GetMaskBand().ReadRaster(x, y, 16, 16)
    return {
        "datasetId": job["datasetId"],
        "prepared": True,
        "preparedPath": str(target),
        "sourcePath": str(source),
        "sourceSha256": source_sha,
        "descriptorSha256": sha(target),
        "overviewBytes": lowres.stat().st_size,
        "sourceCodeSha256": sha(Path(__file__)),
        "nativePixelsVerified": True,
        "preparedAt": time.time(),
    }


def main():
    receipts = []
    for job in json.loads(JOB_FILE.read_text()):
        receipt = prepare(job)
        receipts.append(receipt)
        (JOB_FILE.parent / "overview-direct-receipts.json").write_text(
            json.dumps(receipts, indent=2)
        )
        print(json.dumps(receipt), flush=True)
    print(json.dumps({"complete": True}), flush=True)


if __name__ == "__main__":
    main()
