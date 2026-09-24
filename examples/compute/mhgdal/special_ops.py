"""Hyperspectral and batch raster adaptations of the supplied implementation."""

import csv
import tempfile
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr, osr
from raster_ops import raster, vector, numbers, indices, archive, copy_image


def sam(context):
    src = raster(context)
    p = context.parameters
    with context.input_path("spectra").open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        header = next(reader)
        table = np.asarray([[float(x) for x in row] for row in reader])
    if (
        len(header) < 2
        or header[0].lower() != "wavelength"
        or table.ndim != 2
        or table.shape != (src.RasterCount, len(header))
        or len(header) > 256
    ):
        raise ValueError(
            "光谱表首列为wavelength，其余列每列一类，行数必须等于影像波段数"
        )
    if not np.isfinite(table).all() or np.any(np.diff(table[:, 0]) <= 0):
        raise ValueError("参考光谱数值须有限，波长严格递增")
    low, high = p["wave_min"], p["wave_max"]
    selected = (table[:, 0] >= low) & ((table[:, 0] <= high) if high else True)
    if not selected.any():
        raise ValueError("波长范围没有对应波段")
    thresholds = numbers(p["thresholds"])
    if not thresholds or any(not 0 < x <= np.pi for x in thresholds):
        raise ValueError("光谱角阈值须大于0且不超过π")
    count = table.shape[1] - 1
    if len(thresholds) < count:
        thresholds += [thresholds[0]] * (count - len(thresholds))
    if len(thresholds) != count:
        raise ValueError("阈值数量超过类别数")
    dst = gdal.GetDriverByName("GTiff").Create(
        str(context.output_path("result.tif")),
        src.RasterXSize,
        src.RasterYSize,
        1,
        gdal.GDT_Byte,
    )
    dst.SetProjection(src.GetProjection())
    dst.SetGeoTransform(src.GetGeoTransform())
    dst.GetRasterBand(1).SetNoDataValue(0)
    for row in range(src.RasterYSize):
        data = (
            src.ReadAsArray(0, row, src.RasterXSize, 1)
            .reshape(src.RasterCount, src.RasterXSize)
            .astype(float)
        )
        stable = np.ones(data.shape, dtype=bool)
        stable[1:] = (data[1:] >= data[:-1] / 2) & (data[1:] <= data[:-1] * 2)
        angles = []
        for k in range(count):
            reference = table[:, k + 1, None]
            valid = (
                selected[:, None]
                & stable
                & (data > 0)
                & (reference > 0)
                & np.isfinite(data)
            )
            x = np.where(valid, data, 0)
            y = np.where(valid, reference, 0)
            denominator = np.sqrt((x * x).sum(axis=0) * (y * y).sum(axis=0))
            cosine = np.divide(
                (x * y).sum(axis=0),
                denominator,
                out=np.zeros(src.RasterXSize),
                where=denominator > 0,
            )
            angles.append(
                np.where(denominator > 0, np.arccos(np.clip(cosine, -1, 1)), np.inf)
            )
        angles = np.asarray(angles)
        best = angles.argmin(axis=0)
        minimum = angles[best, np.arange(src.RasterXSize)]
        classes = np.where(minimum < np.asarray(thresholds)[best], best + 1, 0).astype(
            "uint8"
        )
        dst.GetRasterBand(1).WriteArray(classes[None, :], 0, row)
    dst = None


def batch_subset(context):
    src = raster(context)
    points = vector(context)
    layer = points.GetLayer(0)
    width = context.parameters["width"]
    target = osr.SpatialReference(wkt=src.GetProjection())
    source = layer.GetSpatialRef()
    if source is None:
        raise ValueError("输入点缺少坐标系")
    target.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    source.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    transform = osr.CoordinateTransformation(source, target)
    inverse = gdal.InvGeoTransform(src.GetGeoTransform())
    if layer.GetFeatureCount() > 1000:
        raise ValueError("单任务最多裁剪1000个点")
    with tempfile.TemporaryDirectory(
        dir=context.output_path("result.zip").parent
    ) as temp:
        boundary_ds = None
        if context.parameters["export_bounds"]:
            boundary_ds = ogr.GetDriverByName("GPKG").CreateDataSource(
                str(Path(temp) / "bounds.gpkg")
            )
            boundary_layer = boundary_ds.CreateLayer(
                "data", srs=target, geom_type=ogr.wkbPolygon
            )
            boundary_layer.CreateField(ogr.FieldDefn("tile", ogr.OFTString))
        count = 0
        for index, f in enumerate(layer):
            geom = f.GetGeometryRef().Clone()
            if ogr.GT_Flatten(geom.GetGeometryType()) != ogr.wkbPoint:
                raise ValueError("批量裁剪需要点数据")
            geom.Transform(transform)
            x, y = gdal.ApplyGeoTransform(inverse, geom.GetX(), geom.GetY())
            x0 = int(np.floor(x - width / 2))
            y0 = int(np.floor(y - width / 2))
            if (
                x0 < 0
                or y0 < 0
                or x0 + width > src.RasterXSize
                or y0 + width > src.RasterYSize
            ):
                raise ValueError("裁剪窗口越出影像边界，请减小宽度或调整中心点")
            name = f"tile_{index:04d}.tif"
            tile = copy_image(src, Path(temp) / name, srcWin=[x0, y0, width, width])
            del tile
            count += 1
            if boundary_ds:
                ring = ogr.Geometry(ogr.wkbLinearRing)
                for px, py in [
                    (x0, y0),
                    (x0 + width, y0),
                    (x0 + width, y0 + width),
                    (x0, y0 + width),
                    (x0, y0),
                ]:
                    ring.AddPoint_2D(
                        *gdal.ApplyGeoTransform(src.GetGeoTransform(), px, py)
                    )
                polygon = ogr.Geometry(ogr.wkbPolygon)
                polygon.AddGeometry(ring)
                feature = ogr.Feature(boundary_layer.GetLayerDefn())
                feature.SetField("tile", name)
                feature.SetGeometry(polygon)
                boundary_layer.CreateFeature(feature)
        boundary_ds = None
        if not count:
            raise ValueError("没有裁剪点")
        archive(temp, context.output_path("result.zip"))


def core_unroll(context):
    src = raster(context)
    mask = raster(context, "mask")
    p = context.parameters
    if (src.RasterXSize, src.RasterYSize) != (
        mask.RasterXSize,
        mask.RasterYSize,
    ) or mask.RasterCount != 1:
        raise ValueError("原图与隔板图尺寸须一致，隔板图须单波段")
    selected = np.isin(mask.ReadAsArray(), indices(p["values"], 255))
    counts = selected.sum(axis=1)
    height, width = selected.shape
    middle = height // 2
    upper = np.flatnonzero(counts[: middle + 1] > width / 5)
    lower = np.flatnonzero(counts[middle:] > width / 5)
    if not len(upper) or not len(lower):
        raise ValueError("未识别到上下隔板边界")
    top = int(upper[-1] + 1)
    bottom = int(middle + lower[0] - 1)
    if bottom <= top:
        raise ValueError("隔板之间没有有效岩心区域")
    columns = selected[top : bottom + 1].mean(axis=0) > p["threshold"]
    # Preserve source's separator-to-next-separator strip construction.
    separators = []
    start = 0
    for x in range(1, width):
        if start is None and columns[x]:
            start = x
        if start is not None and columns[x - 1] and not columns[x]:
            separators.append((start, x))
            start = None
    if not separators:
        raise ValueError("没有检测到纵向隔板")
    separators.append((width, width))
    strips = [
        (separators[i][0], separators[i + 1][1]) for i in range(len(separators) - 1)
    ]
    output_width = max(b - a for a, b in strips)
    strips = [(a, b) for a, b in strips if (b - a) * 2 >= output_width]
    strip_height = bottom - top
    with tempfile.TemporaryDirectory(
        dir=context.output_path("result.zip").parent
    ) as temp:
        dst = gdal.GetDriverByName("GTiff").Create(
            str(Path(temp) / "core.tif"),
            output_width,
            strip_height * len(strips),
            src.RasterCount,
            src.GetRasterBand(1).DataType,
        )
        gt = list(mask.GetGeoTransform())
        gt[0] = 0
        gt[3] = p["initial_y"]
        dst.SetGeoTransform(gt)
        for index, (left, right) in enumerate(strips):
            for b in range(1, src.RasterCount + 1):
                dst.GetRasterBand(b).WriteArray(
                    src.GetRasterBand(b).ReadAsArray(
                        left, top, right - left, strip_height
                    ),
                    0,
                    index * strip_height,
                )
        dst = None
        (Path(temp) / "README.txt").write_text(
            "岩心展开影像使用局部坐标，不是地理定位影像。条带自左向右依次纵向拼接。",
            encoding="utf-8",
        )
        archive(temp, context.output_path("result.zip"))
