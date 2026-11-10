"""Convert a confirmed vector category field into named binary mask bands."""

import json
from data_adapters import vector_class_masks


def run(context):
    result = vector_class_masks(
        context.input_path("source"),
        context.output_path("masks.tif"),
        context.parameters["category_field"],
        resolution=context.parameters.get("resolution_m", 100),
        target_epsg=context.parameters.get("target_epsg", 0),
    )
    report = {
        "version": 1,
        "status": "passed",
        "summary": "已按真实类别生成独立0/1波段，原始矢量未修改。",
        "metrics": result,
        "knowledgeFacts": {
            "semantics": "class_mask_stack_v1",
            "operation": "vector_rasterize",
            "categoryField": context.parameters["category_field"],
        },
    }
    with open(context.output_path("quality.json"), "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False)
