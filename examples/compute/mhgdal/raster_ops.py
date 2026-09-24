"""Portable GDAL operations executed only inside a compute task process."""

import math
import tempfile
import zipfile
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()
gdal.SetCacheMax(128 * 1024**2)


def numbers(text, cast=float):
    return [
        cast(x.strip()) for x in str(text).replace(",", ";").split(";") if x.strip()
    ]


def indices(text, maximum):
    if not str(text).strip():
        return list(range(1, maximum + 1))
    result = []
    for part in str(text).split(";"):
        bounds = part.split("~")
        start = int(bounds[0])
        end = int(bounds[-1])
        if len(bounds) > 2 or not 0 <= start <= end <= maximum:
            raise ValueError("范围或编号无效")
        result.extend(range(start, end + 1))
    return result


def raster(context, key="raster"):
    ds = gdal.Open(str(context.input_path(key)))
    if ds is None:
        raise ValueError("无法打开输入影像")
    return ds


def vector(context):
    ds = gdal.OpenEx(str(context.input_path("vector")), gdal.OF_VECTOR)
    if ds is None:
        raise ValueError("无法打开输入矢量")
    return ds


def copy_image(source, path, **kwargs):
    ds = gdal.Translate(
        str(path),
        source,
        format="GTiff",
        creationOptions=["COMPRESS=DEFLATE", "BIGTIFF=IF_SAFER"],
        **kwargs,
    )
    if ds is None:
        raise ValueError("影像转换失败")
    ds.FlushCache()
    return ds


def bounds(context, projection):
    values = numbers(context.parameters.get("bounds", ""))
    if values:
        if (
            len(values) != 4
            or not all(math.isfinite(x) for x in values)
            or values[0] >= values[2]
            or values[1] >= values[3]
        ):
            raise ValueError("范围须为xmin;ymin;xmax;ymax")
        return values
    if "reference" in context.inputs:
        ref = raster(context, "reference")
        if ref.GetProjection() != projection:
            left = osr.SpatialReference(wkt=ref.GetProjection())
            right = osr.SpatialReference(wkt=projection)
            if not left.IsSame(right):
                raise ValueError("参考影像与输入数据坐标系须一致")
        gt = ref.GetGeoTransform()
        corners = [
            gdal.ApplyGeoTransform(gt, x, y)
            for x in (0, ref.RasterXSize)
            for y in (0, ref.RasterYSize)
        ]
        return [
            min(p[0] for p in corners),
            min(p[1] for p in corners),
            max(p[0] for p in corners),
            max(p[1] for p in corners),
        ]
    return None


def archive(folder, target):
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as output:
        for path in sorted(Path(folder).iterdir()):
            if path.is_file():
                output.write(path, path.name)


def polygonize(context, footprint=False):
    src = raster(context)
    band = src.GetRasterBand(context.parameters["band"])
    target = ogr.GetDriverByName("GPKG").CreateDataSource(
        str(context.output_path("result.gpkg"))
    )
    layer = target.CreateLayer(
        "data",
        srs=osr.SpatialReference(wkt=src.GetProjection()),
        geom_type=ogr.wkbPolygon,
    )
    layer.CreateField(ogr.FieldDefn("value", ogr.OFTInteger64))
    mask = band.GetMaskBand()
    if footprint:
        mem = gdal.GetDriverByName("MEM").Create(
            "", src.RasterXSize, src.RasterYSize, 1, gdal.GDT_Byte
        )
        mem.SetGeoTransform(src.GetGeoTransform())
        mem.SetProjection(src.GetProjection())
        mem.GetRasterBand(1).WriteArray((mask.ReadAsArray() != 0).astype("uint8"))
        band = mem.GetRasterBand(1)
    gdal.Polygonize(band, mask, layer, 0, [])
    target = None


def rasterize(context):
    src = vector(context)
    layer = src.GetLayer(0)
    p = context.parameters
    srs = layer.GetSpatialRef()
    if srs is None:
        raise ValueError("输入矢量缺少坐标系")
    extent = bounds(context, srs.ExportToWkt())
    if extent is None:
        e = layer.GetExtent()
        extent = [e[0], e[2], e[1], e[3]]
    resolution = p["resolution"] or (extent[2] - extent[0]) / p["width"]
    if resolution <= 0:
        raise ValueError("无法确定有效分辨率")
    width = math.ceil((extent[2] - extent[0]) / resolution)
    height = math.ceil((extent[3] - extent[1]) / resolution)
    if width * height > 100_000_000:
        raise ValueError("输出像元过多，请降低分辨率")
    field = p["field"]
    if field and layer.GetLayerDefn().GetFieldIndex(field) < 0:
        raise ValueError("赋值字段不存在")
    burn_source = src
    if p["boundary"]:
        burn_source = ogr.GetDriverByName("Memory").CreateDataSource("")
        lines = burn_source.CreateLayer("data", srs=srs, geom_type=ogr.wkbUnknown)
        if field:
            lines.CreateField(
                layer.GetLayerDefn().GetFieldDefn(
                    layer.GetLayerDefn().GetFieldIndex(field)
                )
            )
        for f in layer:
            nf = ogr.Feature(lines.GetLayerDefn())
            nf.SetGeometry(f.GetGeometryRef().Boundary())
            if field:
                nf.SetField(field, f.GetField(field))
            lines.CreateFeature(nf)
        layer = lines
    dst = gdal.GetDriverByName("GTiff").Create(
        str(context.output_path("result.tif")), width, height, 1, gdal.GDT_Float64
    )
    dst.SetProjection(srs.ExportToWkt())
    dst.SetGeoTransform([extent[0], resolution, 0, extent[3], 0, -resolution])
    dst.GetRasterBand(1).Fill(0)
    gdal.RasterizeLayer(
        dst,
        [1],
        layer,
        burn_values=[1],
        options=["ATTRIBUTE=" + field] if field else [],
    )
    dst = None


def raster_operation(context, operation):
    src = raster(context)
    p = context.parameters
    output = context.output_path("result.tif")
    if operation in {"pyramid", "remove-pyramid"}:
        dst = copy_image(src, output)
        if operation == "pyramid":
            levels = numbers(p["levels"], int)
            if not levels or any(x < 2 or x > 65536 for x in levels):
                raise ValueError("金字塔倍数须为2至65536")
            dst.BuildOverviews(p["resampling"], sorted(set(levels)))
        dst = None
    elif operation == "raster-subset":
        extent = bounds(context, src.GetProjection())
        bands = indices(p["bands"], src.RasterCount)
        if not bands or min(bands) < 1:
            raise ValueError("波段从1开始")
        opts = dict(bandList=bands)
        if extent:
            opts["projWin"] = [extent[0], extent[3], extent[2], extent[1]]
        copy_image(src, output, **opts)
    elif operation == "stack":
        sources = [src] + [
            raster(context, "raster" + str(i))
            for i in range(2, 9)
            if "raster" + str(i) in context.inputs
        ]
        if any(
            (s.RasterXSize, s.RasterYSize, s.GetGeoTransform(), s.GetProjection())
            != (
                src.RasterXSize,
                src.RasterYSize,
                src.GetGeoTransform(),
                src.GetProjection(),
            )
            for s in sources
        ):
            raise ValueError("合并影像须具有相同坐标系、范围、分辨率和像素尺寸")
        count = sum(s.RasterCount for s in sources)
        if src.RasterXSize * src.RasterYSize * count > 100_000_000:
            raise ValueError("输出规模超过限制")
        dtype = np.result_type(
            *[
                gdal.GetDataTypeName(s.GetRasterBand(b).DataType)
                .replace("Byte", "uint8")
                .lower()
                for s in sources
                for b in range(1, s.RasterCount + 1)
            ]
        )
        from osgeo import gdal_array

        dst = gdal.GetDriverByName("GTiff").Create(
            str(output),
            src.RasterXSize,
            src.RasterYSize,
            count,
            gdal_array.NumericTypeCodeToGDALTypeCode(dtype),
        )
        dst.SetProjection(src.GetProjection())
        dst.SetGeoTransform(src.GetGeoTransform())
        index = 1
        for s in sources:
            for b in range(1, s.RasterCount + 1):
                for y in range(0, s.RasterYSize, 128):
                    dst.GetRasterBand(index).WriteArray(
                        s.GetRasterBand(b).ReadAsArray(
                            0, y, s.RasterXSize, min(128, s.RasterYSize - y)
                        ),
                        0,
                        y,
                    )
                index += 1
        dst = None
    elif operation == "format":
        formats = {
            "GTiff": ("tif", None),
            "HFA": ("img", None),
            "ENVI": ("dat", None),
            "BMP": ("bmp", 1),
            "JPEG": ("jpg", 1),
            "PNG": ("png", 1),
        }
        ext, byte = formats[p["format"]]
        if byte and (
            src.RasterCount not in (1, 3)
            or any(
                src.GetRasterBand(b).DataType != gdal.GDT_Byte
                for b in range(1, src.RasterCount + 1)
            )
        ):
            raise ValueError("图像格式需1或3个Byte波段，请先选择波段并转换数据类型")
        with tempfile.TemporaryDirectory(
            dir=context.output_path("result.zip").parent
        ) as temp:
            ds = gdal.Translate(
                str(Path(temp) / ("result." + ext)), src, format=p["format"]
            )
            ds.FlushCache()
            del ds
            archive(temp, context.output_path("result.zip"))
    elif operation == "axi":
        low, high = p["minimum"], p["maximum"]
        if low > high or (p["dtype"] == "Byte" and not 0 <= low <= high <= 255):
            raise ValueError("有效范围或Byte范围无效")
        dst = copy_image(src, output, outputType=gdal.GetDataTypeByName(p["dtype"]))
        for b in range(1, src.RasterCount + 1):
            for y in range(0, src.RasterYSize, 128):
                data = (
                    src.GetRasterBand(b)
                    .ReadAsArray(0, y, src.RasterXSize, min(128, src.RasterYSize - y))
                    .astype(float)
                )
                data[~np.isfinite(data) | (data < low) | (data > high)] = low
                if p["dtype"] == "Byte":
                    data = np.trunc(data).astype("uint8")
                dst.GetRasterBand(b).WriteArray(data, 0, y)
        dst = None
    else:
        raise ValueError("未知影像操作")


def contour(context):
    src = raster(context)
    p = context.parameters
    band = src.GetRasterBand(p["band"])
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(
        str(context.output_path("result.gpkg"))
    )
    layer = ds.CreateLayer(
        "data",
        srs=osr.SpatialReference(wkt=src.GetProjection()),
        geom_type=ogr.wkbMultiPolygon if p["polygons"] else ogr.wkbLineString,
    )
    for name, kind in [
        ("id", ogr.OFTInteger),
        ("minimum", ogr.OFTReal),
        ("maximum", ogr.OFTReal),
    ]:
        layer.CreateField(ogr.FieldDefn(name, kind))
    levels = numbers(p["levels"])
    opts = ["ID_FIELD=0"]
    opts += (
        ["FIXED_LEVELS=" + ",".join(map(str, levels))]
        if levels
        else ["LEVEL_INTERVAL=" + str(p["interval"]), "LEVEL_BASE=" + str(p["base"])]
    )
    opts += (
        ["POLYGONIZE=YES", "ELEV_FIELD_MIN=1", "ELEV_FIELD_MAX=2"]
        if p["polygons"]
        else ["ELEV_FIELD=1"]
    )
    if p["use_nodata"] and band.GetNoDataValue() is not None:
        opts.append("NODATA=" + str(band.GetNoDataValue()))
    gdal.ContourGenerateEx(band, layer, options=opts)
    ds = None
