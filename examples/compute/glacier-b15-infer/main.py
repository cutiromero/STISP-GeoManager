"""Run the delivered b15 forward pass in the provisioned model runtime."""

import json
import os
from pathlib import Path

from operator_sdk import OperatorFailure, fail

from run_glacier_inference import (
    ARCH_SHA256,
    WEIGHTS_SHA256,
    Profile,
    build_predictor,
    classify_geotiff,
)

# Frozen engineering configuration; this does not specify the training convention.
PROFILE = Profile.parse(
    {
        "schemaVersion": 1,
        "purpose": "engineering",
        "evidence": "交付原波段顺序与原始DN；工程试运行，尚未核验训练输入规约",
        "bands": list(range(1, 16)),
        "gain": [1] * 15,
        "bias": [0] * 15,
        "tile": 256,
        "halo": 0,
        "edge": "constant",
        "fill": 0,
        "mask": "trust_all_valid_metadata",
        "stitch": "center_crop",
    }
)


def run(context):
    predictor = None

    def predict(batch):
        nonlocal predictor
        if predictor is None:
            root = os.environ.get("GEOMANAGER_MODEL_ASSETS")
            name = os.environ.get("GEOMANAGER_MODEL_FILE")
            if (
                not root
                or not name
                or os.environ.get("GEOMANAGER_MODEL_SHA256") != WEIGHTS_SHA256
                or not os.environ.get("CUDA_VISIBLE_DEVICES")
            ):
                fail(context, "B15_RUNTIME", "冰川模型资产或受管GPU未就绪。")
            try:
                with (Path(root) / name).open("rb") as weights:
                    predictor = build_predictor(weights, "cuda")
            except (ValueError, RuntimeError, OSError) as error:
                fail(context, "B15_RUNTIME", str(error))
        return predictor(batch)

    try:
        stats = classify_geotiff(
            context.input_path("image"),
            context.output_path("classification.tif"),
            PROFILE,
            predict,
        )
    except OperatorFailure:
        raise
    except (ValueError, OSError) as error:
        fail(
            context,
            "B15_SOURCE_REJECTED",
            str(error),
            inputs=["image"],
            remedy="replace_data",
        )
    context.output_path("quality.json").write_text(
        json.dumps(
            {
                "version": 1,
                "status": "passed",
                "summary": (
                    "按影像标记排除缺测像元。"
                    if stats["hasExplicitMask"]
                    else "影像未标记缺测像元，按整幅影像计算。"
                ),
                "metrics": stats,
                "knowledgeFacts": {
                    "coverageBasis": "source_mask"
                    if stats["hasExplicitMask"]
                    else "image_extent",
                    "purpose": PROFILE.purpose,
                    "profileSha256": PROFILE.sha256,
                    "checkpointSha256": WEIGHTS_SHA256,
                    "architectureSha256": ARCH_SHA256,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
