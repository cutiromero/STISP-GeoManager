"""Normalize declared raster categories without a domain-specific class list."""

import json
from data_adapters import binary_raster_masks


def run(context):
    labels = json.loads(context.parameters.get("class_labels", "{}"))
    if not isinstance(labels, dict):
        raise ValueError("class_labels必须为类别值到名称的JSON对象")
    result = binary_raster_masks(
        context.input_path("source"),
        context.output_path("masks.tif"),
        label=context.parameters.get("label", ""),
        class_labels=labels,
    )
    report = {
        "version": 1,
        "status": "passed",
        "summary": "已保留实际类别名称并生成0/1波段，原始栅格未修改。",
        "metrics": result,
        "knowledgeFacts": {
            "semantics": "class_mask_stack_v1",
            "operation": "raster_class_masks",
        },
    }
    with open(context.output_path("quality.json"), "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False)
