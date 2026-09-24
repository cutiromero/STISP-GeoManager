"""MHGDAL tool manifests. Source exports mapped to portable compute packages."""

from copy import deepcopy


def inp(key, label, kind="raster", required=True):
    return dict(key=key, label=label, kind=kind, required=required)


def param(key, label, kind, default, **kw):
    return dict(key=key, label=label, type=kind, default=default, required=default != "", **kw)


def out(key="result", kind="raster", file="result.tif", required=True):
    return dict(
        key=key,
        label={"result": "计算结果", "polygons": "保留面", "points": "小面中心点"}.get(
            key, key
        ),
        kind=kind,
        file=file,
        required=required,
    )


R = inp("raster", "输入影像")
V = inp("vector", "输入矢量", "vector")
REF = inp("reference", "范围参考影像（可选）", required=False)
B = param("band", "处理波段", "band", 1, input="raster")
BOUNDS = param("bounds", "范围 xmin;ymin;xmax;ymax（留空使用参考或全部）", "string", "")
VOUT = out(kind="vector", file="result.gpkg")
TOOLS = []


def add(key, name, source, inputs, parameters, outputs=None, description=""):
    TOOLS.append(
        dict(
            key=key,
            source=source,
            category="MHGDAL 矢量工具"
            if inputs[0]["kind"] == "vector"
            else "MHGDAL 栅格工具",
            manifest=dict(
                schemaVersion=1,
                identifier="mhgdal-" + key,
                name=name,
                version="1.0.0",
                description=description
                or name + "；按任务生成独立结果，保留输入数据。",
                author="MHGDALBasicAlgorithms / 平台适配",
                runtime="python-geospatial-v1",
                deterministic=True,
                timeoutSeconds=1800,
                inputs=deepcopy(inputs),
                parameters=deepcopy(parameters),
                outputs=deepcopy(outputs or [out()]),
            ),
        )
    )


add("polygonize", "栅格矢量化", "MHPolygonizeImage", [R], [B], [VOUT])
add("footprint", "影像有效范围提取", "MHGetValidPolygon", [R], [B], [VOUT])
add(
    "simplify",
    "矢量简化",
    "MHPolygonSimply",
    [V],
    [param("tolerance", "简化容差（数据坐标单位）", "number", 1.0, min=0)],
    [VOUT],
    "Douglas–Peucker简化并保持拓扑；使用显式容差，单位与输入坐标一致。",
)
add(
    "rasterize",
    "矢量栅格化",
    "MHRasterizeShp",
    [V, REF],
    [
        param("resolution", "像元大小（坐标单位；0按宽度计算）", "number", 0, min=0),
        param("width", "输出宽度（像素）", "integer", 1024, min=1, max=10000),
        param("field", "赋值字段（留空填1）", "string", ""),
        param("boundary", "仅栅格化边界", "boolean", False),
    ],
)
add("polygon-line", "面转线", "MHPolygon2Line", [V], [], [VOUT])
add(
    "small-polygons",
    "小面转中心点",
    "MHPolygon2PointByArea",
    [V],
    [param("area", "面积阈值（坐标单位的平方）", "number", 100, min=0)],
    [
        out("polygons", "vector", "polygons.gpkg", False),
        out("points", "vector", "points.gpkg", False),
    ],
)
add("line-polygon", "闭合线转面", "MHLine2Polygon", [V], [], [VOUT])
add(
    "pyramid",
    "建立影像金字塔",
    "MHGenImgPyramid",
    [R],
    [
        param("levels", "缩小倍数（分号分隔）", "string", "2;4;8;16"),
        param(
            "resampling",
            "重采样方式",
            "enum",
            "NEAREST",
            choices=["NEAREST", "GAUSS", "CUBIC", "AVERAGE", "MODE"],
        ),
    ],
)
add(
    "remove-pyramid",
    "删除影像金字塔",
    "MHDelImgPyramid",
    [R],
    [],
    description="输出不带金字塔的影像副本，原影像保持不变。",
)
add(
    "stack",
    "影像波段合并",
    "MHLayerStack",
    [R]
    + [
        inp("raster" + str(i), "附加影像" + str(i), required=i == 2)
        for i in range(2, 9)
    ],
    [],
)
add(
    "raster-subset",
    "影像范围与波段裁剪",
    "MHImgSubset",
    [R, REF],
    [BOUNDS, param("bands", "波段顺序（如1;3~5;2；留空全部）", "string", "")],
)
add("vector-subset", "矢量范围提取", "MHFeaSubset", [V, REF], [BOUNDS], [VOUT])
add(
    "format",
    "影像格式转换",
    "MHImgChangeFormat",
    [R],
    [
        param(
            "format",
            "输出格式",
            "enum",
            "GTiff",
            choices=["GTiff", "HFA", "ENVI", "BMP", "JPEG", "PNG"],
        )
    ],
    [out(kind="archive", file="result.zip")],
    "转换为所选格式，主文件及配套地理信息文件一起下载。BMP/JPEG/PNG要求Byte数据及兼容波段数。",
)
add(
    "batch-subset",
    "按点批量裁剪影像",
    "MHImgBatchSubset",
    [R, inp("vector", "裁剪中心点", "vector")],
    [
        param("width", "每块宽高（像素）", "integer", 256, min=1, max=10000),
        param("export_bounds", "同时导出裁剪范围", "boolean", True),
    ],
    [out(kind="archive", file="result.zip")],
)
add(
    "contour",
    "等值线与等值面",
    "MHImgGenContourLineOrPolygon",
    [R],
    [
        B,
        param("interval", "等值间隔", "number", 10, min=0.000001),
        param("base", "基准值", "number", 0),
        param("levels", "固定等值列表（留空使用间隔）", "string", ""),
        param("use_nodata", "排除NoData", "boolean", True),
        param("polygons", "生成等值面", "boolean", False),
    ],
    [VOUT],
)
add(
    "axi",
    "阿希堆积数据转换",
    "MHImgAXiDataChangeFormat",
    [R],
    [
        param("minimum", "有效最小值", "number", 0),
        param("maximum", "有效最大值", "number", 200),
        param("dtype", "输出类型", "enum", "Byte", choices=["Byte", "Float32"]),
    ],
    description="沿用原算法：超出最小/最大范围的值均设为最小值；Byte范围须位于0–255。",
)
for key, name, source in [
    ("sam", "光谱角分类", "MHImgSAMCls"),
    ("plastics", "塑料隔板识别", "MHImgPlasticsIdentify"),
]:
    add(
        key,
        name,
        source,
        [R, inp("spectra", "参考光谱表（首列wavelength，其余每列一个类别）", "table")],
        [
            param("wave_min", "波长下限（0为不限制）", "number", 0, min=0),
            param("wave_max", "波长上限（0为不限制）", "number", 0, min=0),
            param("thresholds", "各类别光谱角阈值（弧度；分号分隔）", "string", "0.05"),
        ],
        description="按参考光谱列顺序输出1–255类，0为未匹配。沿用原实现的正值及相邻波段突变过滤；参考光谱按影像波段逐行对齐。",
    )
add(
    "core-unroll",
    "岩心隔板分割与拼接",
    "MHImgCutByPlastics",
    [R, inp("mask", "隔板分类影像")],
    [
        param("values", "隔板类别值（如4;6~8）", "string", "4"),
        param("initial_y", "起始纵向坐标", "number", 0),
        param("threshold", "列内隔板比例阈值", "number", 0.2, min=0.0001, max=0.9999),
    ],
    [out(kind="archive", file="result.zip")],
    "按隔板位置展开岩心影像，输出使用岩心局部坐标，下载后使用；不将展开坐标当作地理坐标入库。",
)
add(
    "topology",
    "面要素邻接关系",
    "MHFeatureTopoBuild",
    [V],
    [],
    [out(kind="table", file="result.csv")],
    "按外环共享顶点识别邻接（坐标容差1e-8），输出源要素序号与相邻序号。",
)
add(
    "buffer",
    "矢量缓冲区（距离或字段）",
    "MHFeatureBuffer",
    [V],
    [
        param("distance", "缓冲距离（坐标单位；0使用字段）", "number", 100),
        param("field", "距离字段（使用固定距离时留空）", "string", ""),
        param("accuracy", "圆弧精度", "enum", "中", choices=["低", "中", "高"]),
    ],
    [VOUT],
)
PLACEHOLDERS = [
    ("train", "深度学习训练（待实现）", "MHImgDeepLearningTrain"),
    ("inference", "深度学习测试（待实现）", "MHImgDeepLearningTest"),
]
