"""互花米草三季节RF：原始窗口、真实推理、地表面积与分类成果。"""

import csv
import importlib.metadata
import json
import os
from pathlib import Path

# CONFIGURATION
ROLES = ["march", "august", "december"]


def run(context):
    import joblib
    import rasterio
    from operator_sdk import fail

    for role in ROLES:
        with rasterio.open(context.input_path(role)) as source:
            if source.count != 16 or source.crs is None or source.crs.to_epsg() != 4326:
                fail(
                    context,
                    "SPARTINA_INPUT_INVALID",
                    "请选择三期WGS84的16波段原始影像",
                    remedy="replace_data",
                    inputs=[role],
                )
    if len({context.inputs[role].get("resourceId") for role in ROLES}) != 3:
        fail(
            context,
            "SPARTINA_INPUT_INVALID",
            "三个季节须分别选择对应原始影像",
            remedy="replace_data",
            inputs=ROLES,
        )
    from core import infer

    def progress(stage, value):
        path = context.output_path("__platform_progress.json")
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"stage": stage, "progress": value}))
        temporary.replace(path)

    progress("加载RF模型", 30)
    root = Path(os.environ["GEOMANAGER_MODEL_ASSETS"])
    model = joblib.load(root / os.environ["GEOMANAGER_MODEL_FILE"])
    model.n_jobs = 1
    facts = infer(
        {role: context.input_path(role) for role in ROLES},
        model,
        context.output_dir,
        progress,
    )
    facts.update(
        inputPeriods=[
            ((context.inputs[role].get("observationPeriod") or {}).get("startsAt") or "时间未登记")[:7]
            if (context.inputs[role].get("observationPeriod") or {}).get("precision") == "month"
            else (context.inputs[role].get("observationPeriod") or {}).get("startsAt") or "时间未登记"
            for role in ROLES
        ],
        modelSha256=os.environ["GEOMANAGER_MODEL_SHA256"],
        runtimeDigest=os.environ["GEOMANAGER_RUNTIME_DIGEST"],
        sklearnVersion=importlib.metadata.version("scikit-learn"),
        sourceResourceIds=[context.inputs[role]["resourceId"] for role in ROLES],
        parameters=context.parameters,
    )
    context.output_path("result.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=2)
    )
    with context.output_path("statistics.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(facts["statistics"]))
        writer.writeheader()
        writer.writerow(facts["statistics"])
    valid = facts["validPixelCount"] > 0
    context.output_path("quality.json").write_text(
        json.dumps(
            {
                "version": 1,
                "status": "passed" if valid else "needs_review",
                "summary": "原始网格、分类编码、共同有效区和椭球面积检查完成。",
                "metrics": facts["statistics"],
                "knowledgeFacts": {"spartina": facts},
            },
            ensure_ascii=False,
        )
    )
    progress("分类与统计已生成", 84)
