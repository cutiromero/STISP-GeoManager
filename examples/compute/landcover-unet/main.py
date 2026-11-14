"""环江RGB地表解译：五类UNet、后处理和具有固定优先级的分类合成。"""

import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

from operator_sdk import fail

# ==================== CONFIGURATION ====================
ROOT = Path(__file__).parent
CLASS_NAMES = {
    "building": "建筑",
    "water": "水体",
    "farmland": "耕地",
    "forest": "林地",
    "road": "道路",
}
# =======================================================


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def file_digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            value.update(block)
    return value.hexdigest()


def cached_stage(root, key, producer):
    import fcntl

    directory = root / key
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        data = directory / "mask.tif"
        metadata = directory / "receipt.json"
        if data.is_file() and not data.is_symlink() and metadata.is_file():
            try:
                receipt = json.loads(metadata.read_text())
                if receipt["fingerprint"] == key and receipt["sha256"] == file_digest(
                    data
                ):
                    return data, receipt.get("details", {}), True
            except (ValueError, KeyError, OSError):
                pass
        staging = directory / ("work-" + uuid.uuid4().hex)
        staging.mkdir()
        try:
            created, details = producer(staging)
            temporary = directory / "mask.tmp"
            shutil.copyfile(created, temporary)
            checksum = file_digest(temporary)
            temporary.replace(data)
            write_json(
                metadata, {"fingerprint": key, "sha256": checksum, "details": details}
            )
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return data, details, False


def run(context):
    from osgeo import gdal, osr

    gdal.UseExceptions()
    osr.UseExceptions()
    if os.environ.get("PROJ_DATA"):
        osr.SetPROJSearchPaths([os.environ["PROJ_DATA"]])
    image = context.input_path("image")
    dataset = gdal.Open(str(image), gdal.GA_ReadOnly)
    if (
        dataset is None
        or dataset.RasterCount != 3
        or any(dataset.GetRasterBand(i).DataType != gdal.GDT_Byte for i in range(1, 4))
    ):
        fail(
            context,
            "LANDCOVER_INPUT_INVALID",
            "请选择三波段Byte原始RGB影像。",
            remedy="replace_data",
            inputs=["image"],
        )
    if min(dataset.RasterXSize, dataset.RasterYSize) < 1024:
        fail(
            context,
            "LANDCOVER_INPUT_INVALID",
            "影像长宽须至少为1024像元。",
            remedy="replace_data",
            inputs=["image"],
        )
    transform = dataset.GetGeoTransform()
    srs = osr.SpatialReference(wkt=dataset.GetProjection())
    if (
        not srs.IsProjected()
        or abs(srs.GetLinearUnits() - 1) > 1e-8
        or transform[2]
        or transform[4]
        or abs(transform[1] - 2) > 1e-8
        or abs(transform[5] + 2) > 1e-8
    ):
        fail(
            context,
            "LANDCOVER_INPUT_INVALID",
            "请选择北向上、2米分辨率的米制投影影像。",
            remedy="replace_data",
            inputs=["image"],
        )
    original_grid = {
        "width": dataset.RasterXSize,
        "height": dataset.RasterYSize,
        "transform": list(transform),
        "projection": dataset.GetProjection(),
    }
    dataset = None
    selected = context.parameters.get("classes", "all")
    classes = list(CLASS_NAMES) if selected == "all" else selected.split(",")
    if (
        not classes
        or len(set(classes)) != len(classes)
        or not set(classes) <= set(CLASS_NAMES)
    ):
        fail(
            context,
            "LANDCOVER_CLASSES_INVALID",
            "请选择有效且不重复的地物类别。",
            remedy="adjust_parameters",
            parameters=["classes"],
        )
    assets = Path(os.environ["GEOMANAGER_MODEL_ASSETS"])
    config = json.loads((assets / "config/models.json").read_text())
    model_assets = json.loads((assets / "models/model_manifest.json").read_text())
    asset_hashes = {r["name"]: r["sha256"] for r in model_assets["weights"]}
    source_sha = context.inputs["image"]["sha256"]
    code_sha = digest(
        {
            name: file_digest(ROOT / "core" / name)
            for name in ["predictor.py", "networks/UNet.py"]
        }
    )
    cache = Path(
        os.environ.get("GEOMANAGER_MODEL_CACHE", str(context.output_dir / "cache"))
    )
    cache.mkdir(parents=True, exist_ok=True)
    runtime = os.environ.get("GEOMANAGER_RUNTIME_DIGEST", "")
    sys.path.insert(0, str(ROOT / "core"))
    import torch
    import predictor
    from postprocess import process_mask
    from raster_workflow import compose, CODES, COLORS, PRIORITY

    if not torch.cuda.is_available():
        fail(
            context,
            "LANDCOVER_RUNTIME_UNAVAILABLE",
            "当前模型执行卡不可用，请恢复GPU资源后继续。",
            remedy="human_review",
        )
    postprocess = json.loads((assets / "config/postprocess.json").read_text())
    masks = {}
    stages = []

    def progress(stage, value):
        write_json(
            context.output_path("__platform_progress.json"),
            {"stage": stage, "progress": value},
        )

    for index, job in enumerate(
        item for item in config["jobs"] if item["name"] in classes
    ):
        name = job["name"]
        label = CLASS_NAMES[name]
        progress("正在解译" + label, 30 + int(index / len(classes) * 40))
        options = {
            **config["defaults"],
            **job,
            "model_path": str(assets / job["model_path"]),
            "gpu_ids": [0],
            "predict_img_path": str(image.parent),
            "img_type": image.name,
        }
        fingerprint = digest(
            {
                "source": source_sha,
                "model": asset_hashes[name],
                "code": code_sha,
                "runtime": runtime,
                "options": {
                    k: v
                    for k, v in options.items()
                    if k not in {"predict_img_path", "img_type", "model_path"}
                },
            }
        )

        def infer(directory):
            settings = {**options, "output_path": str(directory / "prediction")}
            prediction = predictor.PredictionJob(
                name, predictor.PredictConfig.from_dict(settings)
            )
            predictor.validate_job(prediction)
            result = predictor.run_prediction_job(prediction, [str(image)], False)
            if result["status"] != "completed":
                raise RuntimeError(label + "解译未完成")
            return prediction.output_dir / (image.stem + ".tif"), {
                "status": "completed"
            }

        raw, _, reused = cached_stage(cache, fingerprint, infer)
        progress("整理" + label + "结果", 32 + int((index + 1) / len(classes) * 40))
        clean_fingerprint = digest(
            {
                "raw": fingerprint,
                "postprocess": postprocess[name],
                "code": file_digest(ROOT / "core/postprocess.py"),
            }
        )

        def clean(directory):
            path = directory / "cleaned.tif"
            details = process_mask(raw, path, **postprocess[name])
            details.pop("output", None)
            return path, details

        cleaned, details, clean_reused = cached_stage(cache, clean_fingerprint, clean)
        masks[name] = cleaned
        stages.append(
            {
                "class": name,
                "inferenceReused": reused,
                "postprocessReused": clean_reused,
                "postprocess": details,
                "modelSha256": asset_hashes[name],
            }
        )
    progress("合成地表覆盖分类", 75)
    mode = "complete" if set(classes) == set(CLASS_NAMES) else "extract"
    result = compose(
        image, masks, context.output_path("result.tif"), classes=classes, mode=mode
    )
    if result["grid"] != original_grid:
        raise ValueError("解译输出与原始输入网格不一致")
    legend = [
        {
            "code": CODES[name],
            "name": CLASS_NAMES[name],
            "rgba": list(COLORS[CODES[name]]),
        }
        for name in PRIORITY
        if name in classes
    ]
    if mode == "complete":
        legend.append({"code": 1, "name": "裸地", "rgba": list(COLORS[1])})
    legend += [
        {"code": 0, "name": "未提取区域", "rgba": [0, 0, 0, 0]},
        {"code": 255, "name": "无效区", "rgba": [0, 0, 0, 0]},
    ]
    dataset = gdal.Open(str(context.output_path("result.tif")), gdal.GA_Update)
    dataset.SetMetadataItem(
        "stisp_categorical",
        json.dumps(
            {"schemaVersion": 1, "legend": legend, "transparentValues": [0, 255]},
            ensure_ascii=False,
        ),
    )
    dataset.FlushCache()
    dataset = None
    counts = result["counts"]
    valid = sum(count for key, count in counts.items() if int(key) != 255)
    area_per_pixel = (
        abs(transform[1] * transform[5] - transform[2] * transform[4]) / 1000000
    )
    statistics = [
        {
            "code": row["code"],
            "name": row["name"],
            "pixelCount": counts.get(str(row["code"]), 0),
            "areaKm2": counts.get(str(row["code"]), 0) * area_per_pixel,
            "percent": counts.get(str(row["code"]), 0) / valid * 100 if valid else 0,
            "color": "#" + "".join(f"{v:02X}" for v in row["rgba"][:3]),
        }
        for row in legend
        if row["code"] not in {0, 255}
    ]
    with context.output_path("statistics.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["code", "name", "pixelCount", "areaKm2", "percent", "color"],
        )
        writer.writeheader()
        writer.writerows(statistics)
    metadata = {
        "schemaVersion": 1,
        "status": "completed",
        "mode": mode,
        "sourceResourceId": context.inputs["image"]["resourceId"],
        "inputSha256": source_sha,
        "grid": result["grid"],
        "legend": legend,
        "statistics": statistics,
        "validAreaKm2": valid * area_per_pixel,
        "priority": [CLASS_NAMES[name] for name in PRIORITY],
        "models": stages,
        "runtimeDigest": runtime,
        "maskCounts": counts,
    }
    write_json(context.output_path("result.json"), metadata)
    write_json(
        context.output_path("quality.json"),
        {
            "version": 1,
            "status": "passed" if valid else "needs_review",
            "summary": "原始网格、分类编码与有效区一致，按实际像元完成统计。",
            "metrics": {
                "validAreaKm2": metadata["validAreaKm2"],
                "classCount": len(statistics),
                "inferenceReused": sum(r["inferenceReused"] for r in stages),
            },
            "knowledgeFacts": {"landcover": metadata},
        },
    )
    context.output_path("report.md").write_text(
        "# 地表覆盖解译结果\n\n"
        + "、".join(row["name"] for row in statistics)
        + "\n\n有效统计面积："
        + str(round(metadata["validAreaKm2"], 6))
        + " km²。\n",
        encoding="utf-8",
    )
    progress("分类成果已生成", 84)
