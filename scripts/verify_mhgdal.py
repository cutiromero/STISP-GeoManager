"""Synthetic numerical acceptance for every executable MHGDAL export."""

import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import zipfile
import numpy as np
from osgeo import gdal, ogr, osr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples/compute/mhgdal"))
from catalog import TOOLS  # noqa: E402
from build import build  # noqa: E402


class Context:
    def __init__(self, inputs, parameters, output):
        self.inputs = inputs
        self.parameters = parameters
        self.output = output

    def input_path(self, key):
        return self.inputs[key]

    def output_path(self, name):
        return self.output / name


def fixtures(folder):
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32650)

    def raster(name, data, dtype=gdal.GDT_Float32):
        path = folder / (name + ".tif")
        ds = gdal.GetDriverByName("GTiff").Create(
            str(path), data.shape[2], data.shape[1], data.shape[0], dtype
        )
        ds.SetProjection(srs.ExportToWkt())
        ds.SetGeoTransform([500000, 1, 0, 4000020, 0, -1])
        for i, array in enumerate(data):
            ds.GetRasterBand(i + 1).WriteArray(array)
        ds = None
        return path

    base = np.tile(np.arange(20, dtype="float32"), (20, 1))
    image = raster("raster", np.stack([base, base + 1, base + 2]))
    classes = raster("classes", np.stack([np.where(base < 10, 1, 2)]), gdal.GDT_Byte)
    ds = gdal.Open(str(classes), gdal.GA_Update)
    ds.GetRasterBand(1).SetNoDataValue(0)
    ds = None
    byte = raster("byte", np.stack([base]), gdal.GDT_Byte)
    spectral = raster(
        "spectral",
        np.stack([np.ones((20, 20)), np.ones((20, 20)) * 1.5, np.ones((20, 20)) * 2]),
    )

    def vector(name, wkts):
        path = folder / (name + ".gpkg")
        ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
        layer = ds.CreateLayer("data", srs=srs, geom_type=ogr.wkbUnknown)
        layer.CreateField(ogr.FieldDefn("value", ogr.OFTInteger))
        for i, wkt in enumerate(wkts):
            f = ogr.Feature(layer.GetLayerDefn())
            f.SetField("value", i + 1)
            f.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
            layer.CreateFeature(f)
        ds = None
        return path

    polygons = vector(
        "polygons",
        [
            "POLYGON ((500002 4000002,500006 4000002,500006 4000006,500002 4000006,500002 4000002))",
            "POLYGON ((500006 4000002,500016 4000002,500016 4000012,500006 4000012,500006 4000002))",
        ],
    )
    lines = vector(
        "lines",
        [
            "LINESTRING (500002 4000002,500006 4000002,500006 4000006,500002 4000006,500002 4000002)"
        ],
    )
    points = vector("points", ["POINT (500010 4000010)"])
    spectra = folder / "spectra.csv"
    spectra.write_text(
        "wavelength,class_a,class_b\n500,1,2\n600,1.5,1.5\n700,2,1\n", encoding="utf-8"
    )
    mask = np.zeros((20, 20), dtype="uint8")
    mask[2, :] = 4
    mask[17, :] = 4
    mask[:, 0:2] = 4
    mask[:, 9:11] = 4
    return dict(
        raster=image,
        classes=classes,
        byte=byte,
        spectral=spectral,
        polygons=polygons,
        lines=lines,
        points=points,
        spectra=spectra,
        mask=raster("mask", mask[None], gdal.GDT_Byte),
    )


def case(tool, files):
    key = tool["key"]
    params = {p["key"]: p["default"] for p in tool["manifest"]["parameters"]}
    inputs = {
        i["key"]: files[
            "polygons"
            if i["kind"] == "vector"
            else "spectra"
            if i["kind"] == "table"
            else "raster"
        ]
        for i in tool["manifest"]["inputs"]
        if i["required"]
    }
    if key in {"polygonize", "footprint"}:
        inputs["raster"] = files["classes"]
    if key == "line-polygon":
        inputs["vector"] = files["lines"]
    if key == "small-polygons":
        params["area"] = 50
    if key == "rasterize":
        params.update(resolution=1, field="value")
    if key == "raster-subset":
        params.update(bounds="500002;4000002;500010;4000010", bands="3;1")
    if key == "vector-subset":
        params["bounds"] = "500002;4000003;500003;4000004"
    if key == "batch-subset":
        inputs["vector"] = files["points"]
        params["width"] = 4
    if key in {"sam", "plastics"}:
        inputs["raster"] = files["spectral"]
    if key == "core-unroll":
        inputs["mask"] = files["mask"]
    return inputs, params


def inspect(tool, output):
    key = tool["key"]
    path = output / "result.tif"
    if path.exists():
        ds = gdal.Open(str(path))
        array = ds.ReadAsArray()
        assert np.isfinite(array).all()
        if key == "stack":
            assert ds.RasterCount == 6 and np.array_equal(array[:3], array[3:])
        if key == "raster-subset":
            assert (ds.RasterCount, ds.RasterXSize, ds.RasterYSize) == (
                2,
                8,
                8,
            ) and array[0, 0, 0] == 4
        if key == "rasterize":
            assert set(np.unique(array)) == {0, 1, 2}
        if key in {"sam", "plastics"}:
            assert np.all(array == 1)
        if key == "pyramid":
            assert ds.GetRasterBand(1).GetOverviewCount() > 0
        if key == "remove-pyramid":
            assert ds.GetRasterBand(1).GetOverviewCount() == 0
        if key == "axi":
            assert ds.GetRasterBand(1).DataType == gdal.GDT_Byte
        ds = None
    for spec in tool["manifest"]["outputs"]:
        p = output / spec["file"]
        assert p.is_file(), (key, spec["file"])
        if spec["kind"] == "vector":
            ds = ogr.Open(str(p))
            layer = ds.GetLayer(0)
            assert layer.GetFeatureCount() > 0 and layer.GetSpatialRef() is not None
            geoms = [f.GetGeometryRef().Clone() for f in layer]
            assert all(g.IsValid() and not g.IsEmpty() for g in geoms)
            if key == "polygonize":
                assert sum(g.GetArea() for g in geoms) == 400 and len(geoms) == 2
            if key == "footprint":
                assert sum(g.GetArea() for g in geoms) == 400
            if key == "vector-subset":
                assert len(geoms) == 1
            if key == "small-polygons":
                assert len(geoms) == 1
            if key == "line-polygon":
                assert geoms[0].GetArea() == 16
            if key == "buffer":
                assert geoms[0].GetArea() > 16
            ds = None
        if spec["kind"] == "archive":
            with zipfile.ZipFile(p) as z:
                assert z.testzip() is None and z.namelist()
                if key == "batch-subset":
                    assert (
                        "tile_0000.tif" in z.namelist()
                        and "bounds.gpkg" in z.namelist()
                    )
                if key == "core-unroll":
                    assert "core.tif" in z.namelist()
        if key == "topology":
            assert "0,1" in p.read_text() and "1,0" in p.read_text()


def run_suite(folder):
    files = fixtures(folder)
    results = []
    for tool in TOOLS:
        output = folder / tool["key"]
        output.mkdir()
        package = output / "package"
        package.mkdir()
        with zipfile.ZipFile(io.BytesIO(build(tool))) as z:
            z.extractall(package)
        spec = importlib.util.spec_from_file_location("trial_main", package / "main.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        inputs, params = case(tool, files)
        module.run(Context(inputs, params, output))
        inspect(tool, output)
        results.append(dict(tool=tool["key"], status="passed"))
        print(tool["key"], "passed", flush=True)
    from raster_ops import contour, raster_operation

    alternate = folder / "alternates"
    alternate.mkdir()
    contour(
        Context(
            {"raster": files["raster"]},
            {
                "band": 1,
                "interval": 5,
                "base": 0,
                "levels": "5;10;15",
                "use_nodata": True,
                "polygons": True,
            },
            alternate,
        )
    )
    ds = ogr.Open(str(alternate / "result.gpkg"))
    assert ds.GetLayer(0).GetFeatureCount() > 0
    ds = None
    for format in ["GTiff", "HFA", "ENVI", "BMP", "JPEG", "PNG"]:
        raster_operation(
            Context({"raster": files["byte"]}, {"format": format}, alternate), "format"
        )
        with zipfile.ZipFile(alternate / "result.zip") as z:
            assert z.testzip() is None
    (folder / "results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    return results


if __name__ == "__main__":
    if len(sys.argv) > 1:
        folder = Path(sys.argv[1])
        folder.mkdir(parents=True, exist_ok=True)
        run_suite(folder)
    else:
        with tempfile.TemporaryDirectory() as temp:
            run_suite(Path(temp))
