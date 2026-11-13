"""只读检查到货、完整性与模型接入缺项；不执行模型，不自动安装依赖。"""

from datetime import datetime, timezone
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path, PurePosixPath
import sys
import tomllib

# CONFIGURATION
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config/monitoring.local.toml"
CODE_PATHS = {
    "spartina_alterniflora": (
        "代码/UNET_Predict.py",
        "代码/随机森林预测界面.py",
        "代码/unet_predict_config.json",
    ),
    "wildfire": (
        "climafire-demo/app/model.py",
        "climafire-demo/app/inference.py",
        "climafire-demo/requirements.txt",
    ),
}
MODULES = (
    "torch",
    "rasterio",
    "sklearn",
    "joblib",
    "xarray",
    "zarr",
    "lightning",
    "segmentation_models_pytorch",
    "timm",
    "einops",
)
SCIENTIFIC_REQUIREMENTS = {
    "spartina_unet": (
        "单通道输入的物理含义",
        "训练归一化与NoData规则",
        "类别映射",
        "小研究区一致性验证",
    ),
    "spartina_rf": (
        "48维特征顺序与模型n_features_in_一致",
        "模型classes_与目标类别对应",
        "缺测掩膜与有效区规则",
        "小研究区一致性验证",
    ),
    "wildfire": (
        "11个变量的训练单位与标准化",
        "目标标签与缺测海洋掩膜",
        "w1/w2/w4/w8/w16窗口含义与真实时效",
        "严格加载权重与历史回报验证",
    ),
}


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def safe_source(root, relative):
    parts = PurePosixPath(relative)
    if parts.is_absolute() or ".." in parts.parts or "\\" in relative:
        raise ValueError("清单路径越界")
    result = root.joinpath(*parts.parts)
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError("清单路径越界")
    return result


def inspect(config):
    sources = config["sources"]
    verify = config["verification"]
    manifest_path = Path(sources["manifest"])
    if (
        not manifest_path.is_file()
        or sha256(manifest_path) != verify["manifest_sha256"]
    ):
        raise ValueError("迁移源清单缺失或SHA-256不符，不能据此检查到货")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    files = manifest["files"]
    if (
        len(files) != verify["expected_files"]
        or sum(item["bytes"] for item in files) != verify["expected_logical_bytes"]
    ):
        raise ValueError("源清单覆盖范围与配置不一致")
    result = {
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "interpreter": sys.executable,
        "transferVerified": False,
        "scenes": {},
        "dependencies": {
            name: importlib.util.find_spec(name) is not None for name in MODULES
        },
        "scientificRequirements": SCIENTIFIC_REQUIREMENTS,
    }
    receipt_path = Path(sources["receipt"])
    receipt = json.loads(receipt_path.read_text()) if receipt_path.is_file() else {}
    expected_roots = {key: str(Path(sources[key]).resolve()) for key in CODE_PATHS}
    actual_roots = {
        key: str(Path(value).resolve())
        for key, value in receipt.get("roots", {}).items()
    }
    receipt_valid = (
        receipt.get("complete") is True
        and receipt.get("archive_sha256") == verify["archive_sha256"]
        and receipt.get("manifest_sha256") == verify["manifest_sha256"]
        and receipt.get("files") == len(files)
        and receipt.get("logical_bytes") == verify["expected_logical_bytes"]
        and actual_roots == expected_roots
    )
    for dataset in CODE_PATHS:
        root = Path(sources[dataset])
        selected = [item for item in files if item["dataset"] == dataset]
        missing, different, verified_small = [], [], []
        for item in selected:
            path = safe_source(root, item["relative_path"])
            if not path.is_file():
                missing.append(item["relative_path"])
            elif path.stat().st_size != item["bytes"]:
                different.append(item["relative_path"])
            elif item["bytes"] <= verify["hash_files_up_to_bytes"]:
                if sha256(path) != item["sha256"]:
                    different.append(item["relative_path"])
                else:
                    verified_small.append(item["relative_path"])
        result["scenes"][dataset] = {
            "expectedFiles": len(selected),
            "presentFiles": len(selected) - len(missing),
            "missing": missing,
            "different": different,
            "hashVerifiedSmallFiles": verified_small,
            "filesPresent": not missing and not different,
            "integrityVerified": receipt_valid and not missing and not different,
            "modelExecutable": False,
        }
    result["transferVerified"] = receipt_valid and all(
        item["integrityVerified"] for item in result["scenes"].values()
    )
    result["scientificContracts"] = {}
    for key in SCIENTIFIC_REQUIREMENTS:
        configured = config.get("scientific_contracts", {}).get(key)
        path = Path(configured) if configured else None
        result["scientificContracts"][key] = {
            "supplied": bool(path and path.is_file()),
            "sha256": sha256(path) if path and path.is_file() else None,
            "status": "需按检查清单审核；不自动授予算子发布或执行权限",
        }
    cube = safe_source(
        Path(sources["wildfire"]),
        config.get("wildfire", {}).get(
            "zarr_relative_path", "wildfire/seasfire_v0.4.zarr"
        ),
    )
    wildfire = cube / ".zmetadata"
    coordinates_present = all(
        (cube / variable / "0").is_file()
        for variable in ("time", "latitude", "longitude")
    )
    result["zarrCoordinatesPresent"] = coordinates_present
    if wildfire.is_file():
        metadata = json.loads(wildfire.read_text())["metadata"]
        result["zarr"] = {
            "attributes": metadata.get(".zattrs", {}),
            "time": metadata.get("time/.zattrs", {}),
            "timeShape": metadata.get("time/.zarray", {}).get("shape"),
            "variables": sorted(
                {key.split("/")[0] for key in metadata if not key.startswith(".")}
            ),
        }
    if verify.get("inspect_geospatial_headers"):
        try:
            from osgeo import gdal, ogr
        except ImportError:
            result["geospatialHeaders"] = {
                "status": "当前解释器没有GDAL，不安装依赖；请使用已有GIS环境完成头信息检查"
            }
        else:
            gdal.UseExceptions()
            headers = {}
            root = Path(sources["spartina_alterniflora"])
            for name in (
                "数据/图像分割待预测数据/x.tif",
                "数据/随机森林待预测数据/merged_sat_202503.tif",
                "数据/随机森林待预测数据/merged_sat_202508.tif",
                "数据/随机森林待预测数据/merged_sat_202512.tif",
                "结果/merged_202012.tif",
            ):
                path = root / name
                if not path.is_file():
                    continue
                ds = gdal.Open(str(path))
                headers[name] = {
                    "size": [ds.RasterXSize, ds.RasterYSize],
                    "bands": ds.RasterCount,
                    "geotransform": ds.GetGeoTransform(),
                    "projection": ds.GetProjection(),
                }
                ds = None
            shape = root / "结果/UNet_互花米草.shp"
            if shape.is_file():
                ds = ogr.Open(str(shape))
                if ds:
                    layer = ds.GetLayer()
                    headers[shape.name] = {
                        "features": layer.GetFeatureCount(),
                        "extent": layer.GetExtent(),
                        "observationDate": None,
                    }
            result["geospatialHeaders"] = headers
            if coordinates_present:
                ds = gdal.OpenEx(str(cube), gdal.OF_MULTIDIM_RASTER)
                group = ds.GetRootGroup()
                coordinates = {}
                for name, count, lower, upper in (
                    ("time", 966, 0, 100000),
                    ("latitude", 720, -90, 90),
                    ("longitude", 1440, -180, 180),
                ):
                    values = group.OpenMDArray(name).ReadAsArray().tolist()
                    finite = len(values) == count and all(
                        math.isfinite(value) and lower <= value <= upper
                        for value in values
                    )
                    monotonic = (
                        all(a < b for a, b in zip(values, values[1:]))
                        if name != "latitude"
                        else all(a > b for a, b in zip(values, values[1:]))
                    )
                    coordinates[name] = {
                        "valid": finite and monotonic,
                        "count": len(values),
                        "first": values[:3] if finite else [],
                        "last": values[-3:] if finite else [],
                    }
                result["zarrCoordinates"] = coordinates
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    config_path = parser.parse_args().config
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        result = inspect(config)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        result = {"ready": False, "detail": str(error), "config": str(config_path)}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
