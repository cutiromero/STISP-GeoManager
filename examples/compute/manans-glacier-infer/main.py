"""Extract binary glacier cover on the source grid with the delivered AGRS model."""

import csv
from hashlib import sha256
import json
import os
from pathlib import Path
import re

import numpy as np
import rasterio
from rasterio.windows import Window

from operator_sdk import fail

# Frozen inference profile from the supplied model and 29 July training list.
SHA256 = "b33bb2a0b22dd35060a725fbd3e7afa64ac9d7af0e668b1459e65213dbf0fab6"
ARCHITECTURE_SHA = "63213a4c6c0dd1dbdea99a89be00e79f0ecc9d491afeccb0c74452711b26615a"
PROFILE_SHA = "c30eb376fb7808cbcac8b03afd68896eb2ecdeaec20c86017997ac191671d0a5"
TILE = 256
HALO = 26
BATCH = 8
NODATA = 255
MAX_PIXELS = 121_000_000
LEGEND = [
    {"code": 0, "name": "非冰川", "rgba": [54, 74, 92, 255]},
    {"code": 1, "name": "冰川", "rgba": [93, 216, 255, 255]},
    {"code": NODATA, "name": "无数据", "rgba": [0, 0, 0, 0]},
]


def checked_asset(path, digest):
    contents = path.read_bytes()
    if sha256(contents).hexdigest() != digest:
        raise ValueError(f"资料摘要不一致：{path.name}")
    return contents


def build_predictor():
    import torch

    root, name = (
        os.environ.get("GEOMANAGER_MODEL_ASSETS"),
        os.environ.get("GEOMANAGER_MODEL_FILE"),
    )
    if not root or not name or os.environ.get("GEOMANAGER_MODEL_SHA256") != SHA256:
        raise ValueError("玛纳斯冰川权重配置与发布版本不一致")
    if not os.environ.get("CUDA_VISIBLE_DEVICES") or not torch.cuda.is_available():
        raise ValueError("受管 GPU 尚未分配")
    assets = Path(root)
    architecture = checked_asset(assets / "DLinknet.py", ARCHITECTURE_SHA).decode(
        "utf-8-sig"
    )
    initializer = "models.resnet34(pretrained=True)"
    if architecture.count(initializer) != 1:
        raise ValueError("交付网络的 ResNet34 初始化与核验版本不一致")
    namespace = {"__name__": "manans_agrs_dlinknet"}
    exec(
        compile(
            architecture.replace(initializer, "models.resnet34(weights=None)"),
            "DLinknet.py",
            "exec",
        ),
        namespace,
    )
    profile = json.loads(checked_asset(assets / "normalization.json", PROFILE_SHA))
    mean = torch.tensor(profile["mean"], device="cuda", dtype=torch.float32)[
        None, :, None, None
    ]
    std = torch.tensor(profile["std"], device="cuda", dtype=torch.float32)[
        None, :, None, None
    ]
    with (assets / name).open("rb") as stream:
        state = torch.load(stream, map_location="cpu", weights_only=True)
    model = namespace["DLinkNet34"](num_classes=2, band_num=4)
    model.load_state_dict(
        {key.removeprefix("module."): value for key, value in state.items()},
        strict=True,
    )
    model = model.eval().to("cuda")

    def predict(values):
        with torch.inference_mode():
            batch = torch.from_numpy(values).to("cuda", dtype=torch.float32)
            return model((batch - mean) / std).argmax(dim=1).byte().cpu().numpy()

    return predict


def validate_source(source):
    grid = source.transform
    if (
        source.crs is None
        or source.crs.to_epsg() != 32645
        or source.dtypes != ("uint8",) * 4
        or tuple(
            re.sub(r" \([0-9]+(?:\.[0-9]+)? Nanometers\)$", "", (name or "").strip())
            for name in source.descriptions
        )
        != ("B2", "B3", "B4", "B8")
        or any(
            abs(actual - expected) > 1e-8
            for actual, expected in zip(
                (grid.a, grid.b, grid.d, grid.e), (10, 0, 0, -10)
            )
        )
        or not 0 < source.width * source.height <= MAX_PIXELS
    ):
        raise ValueError("请选择玛纳斯原始影像（四波段 Byte、10 米、UTM 45N）")


def tile_input(source, x, y, width, height):
    left = min(max(0, x - HALO), max(0, source.width - TILE))
    top = min(max(0, y - HALO), max(0, source.height - TILE))
    values = source.read(
        window=Window(left, top, min(TILE, source.width), min(TILE, source.height))
    )
    padded = np.pad(
        values, ((0, 0), (0, TILE - values.shape[1]), (0, TILE - values.shape[2]))
    )
    core = np.s_[y - top : y - top + height, x - left : x - left + width]
    target = Window(x, y, width, height)
    mask = source.dataset_mask(window=target) != 0
    return padded, core, target, mask


def classify(source, output, predict):
    counts = np.zeros(256, dtype=np.int64)
    stride = TILE - 2 * HALO
    with rasterio.open(
        output,
        "w",
        driver="GTiff",
        height=source.height,
        width=source.width,
        count=1,
        crs=source.crs,
        transform=source.transform,
        dtype="uint8",
        nodata=NODATA,
        tiled=True,
        blockxsize=256,
        blockysize=256,
        compress="deflate",
    ) as result:
        result.write_colormap(1, {item["code"]: item["rgba"] for item in LEGEND})
        result.update_tags(
            stisp_categorical=json.dumps(
                {
                    "schemaVersion": 1,
                    "legend": LEGEND,
                    "transparentValues": [NODATA],
                },
                ensure_ascii=False,
            )
        )
        pending = []

        def flush():
            if not pending:
                return
            predictions = predict(np.stack([row[0] for row in pending]))
            for prediction, (_, core, target, mask) in zip(
                predictions, pending, strict=True
            ):
                output_block = np.where(mask, prediction[core], NODATA).astype(np.uint8)
                counts[:] += np.bincount(output_block.ravel(), minlength=256)
                result.write(output_block, 1, window=target)
            pending.clear()

        for y in range(0, source.height, stride):
            for x in range(0, source.width, stride):
                width, height = (
                    min(stride, source.width - x),
                    min(stride, source.height - y),
                )
                item = tile_input(source, x, y, width, height)
                if not item[3].any():
                    result.write(
                        np.full((height, width), NODATA, dtype=np.uint8),
                        1,
                        window=item[2],
                    )
                    counts[NODATA] += width * height
                else:
                    pending.append(item)
                    if len(pending) == BATCH:
                        flush()
        flush()
    return counts


def run(context):
    predictor = None

    def predict(batch):
        nonlocal predictor
        try:
            if predictor is None:
                predictor = build_predictor()
            return predictor(batch)
        except (ValueError, RuntimeError, OSError) as error:
            fail(context, "MANANS_RUNTIME", str(error), remedy="human_review")

    with rasterio.open(context.input_path("image")) as source:
        try:
            validate_source(source)
        except ValueError as error:
            fail(
                context,
                "MANANS_SOURCE",
                str(error),
                inputs=["image"],
                remedy="replace_data",
            )
        counts = classify(source, context.output_path("classification.tif"), predict)
        total = source.width * source.height

    valid = int(counts[0] + counts[1])
    if valid + counts[NODATA] != total:
        fail(
            context,
            "MANANS_RUNTIME",
            "分类像元计数与原始网格不一致",
            remedy="human_review",
        )
    if not valid:
        fail(
            context,
            "MANANS_SOURCE",
            "原始影像没有有效像元",
            inputs=["image"],
            remedy="replace_data",
        )
    glacier = int(counts[1])
    stats = {
        "scene_pixels": total,
        "valid_pixels": valid,
        "nodata_pixels": int(counts[NODATA]),
        "glacier_pixels": glacier,
        "valid_coverage_percent": 100 * valid / total,
        "glacier_percent": 100 * glacier / valid,
        "glacier_area_km2": glacier / 10_000,
    }
    with context.output_path("statistics.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(stats))
        writer.writeheader()
        writer.writerow(stats)
    context.output_path("quality.json").write_text(
        json.dumps(
            {
                "version": 1,
                "status": "passed",
                "summary": "分类图与原始影像同网格；使用源掩膜区分有效非冰川与缺测，面积按原生10米像元计算。",
                "metrics": stats,
                "knowledgeFacts": {
                    "checkpointSha256": SHA256,
                    "normalizationList": "trainlist_0729_glacier_add.txt",
                    "normalizationSha256": PROFILE_SHA,
                    "architectureSha256": ARCHITECTURE_SHA,
                    "bandOrder": "B2/B3/B4/B8",
                    "coverageBasis": "source_mask",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
