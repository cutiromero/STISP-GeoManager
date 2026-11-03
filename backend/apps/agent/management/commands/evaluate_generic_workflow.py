"""Register recall/precision of a finished geology workflow against labelled inputs."""

import csv
import tempfile
from pathlib import Path

import geopandas as gpd
from django.core.management.base import BaseCommand, CommandError

from apps.agent.generic_evaluation import (
    RELATION_KEYS,
    TARGET,
    fault_truth,
    lithology_truth,
    metrics,
    read_issues,
    reported,
    sweep,
)
from apps.agent.geology_generic import MULTI_FAMILY
from apps.agent.models import AgentWorkflow
from apps.agent.workflow_validation import publish_validation
from apps.catalog.models import DataResource
from apps.compute.models import ComputeOutput
from apps.compute.packages import ComputeError
from apps.core.storage import app_path, vector_geopackage_path
from apps.projects.context import ProjectScope, project_scope

SCORE_COLUMNS = [
    ("truth", "真实冲突"),
    ("reported", "报出"),
    ("tp", "正确检出"),
    ("fp", "误报"),
    ("fn", "漏检"),
    ("recall", "查全率"),
    ("precision", "查准率"),
]


def _layer(resource_id):
    resource = DataResource.objects.get(pk=resource_id)
    return gpd.read_file(vector_geopackage_path(), layer=resource.storage_path)


def _section(key, title, summary, first, rows):
    columns = [*first, *SCORE_COLUMNS]
    return {
        "key": key,
        "title": title,
        "summary": summary,
        "columns": [{"key": k, "label": label} for k, label in columns],
        "rows": [{k: row.get(k) for k, _ in columns} for row in rows],
    }


def _write_csv(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class Command(BaseCommand):
    help = (
        "用上传资料中的模拟标签评价检查结果，登记为工作流的独立评价；不进入模型或算子"
    )

    def add_arguments(self, parser):
        parser.add_argument("--workflow-id", required=True)

    def handle(self, **options):
        workflow = AgentWorkflow._base_manager.filter(pk=options["workflow_id"]).first()
        if workflow is None or workflow.workflow_type not in MULTI_FAMILY:
            raise CommandError("请指定一个综合推理或通用地质推理任务")
        scope = ProjectScope(
            (workflow.project_tag_id,), workflow.project_tag_id, workflow.owner_id, True
        )
        with project_scope(scope):
            uploads = workflow.plan.get("uploadInputs") or workflow.plan.get(
                "inputs", {}
            )
            lith = lithology_truth(_layer(uploads["lithology"]))
            faults = (
                fault_truth(_layer(uploads["faults"])) if "faults" in uploads else {}
            )
            check = next(s for s in workflow.plan["stages"] if s["name"] == "check")
            output = ComputeOutput.objects.get(task_id=check["taskId"], key="issues")
            issues = read_issues(app_path(output.path))
            by_rule, by_relation = metrics(reported(issues), lith, faults)
            scan, chosen = sweep(issues, lith, faults)
            summary = {
                "scope": "模拟识别输入（演示）：标签来自上传的模拟资料，指标只代表这组模拟数据，不能作为合同验收结果。",
                "summary": (
                    "按合同三类关系统计本次检查的查全率和查准率；"
                    f"目标为查全率≥{TARGET['recall']:.0%}、查准率≥{TARGET['precision']:.0%}。"
                    f"置信度阈值扫描在同一数据上建议 report_conf_max={chosen['threshold']}"
                    "（未使用独立标定集，正式采用前应另备标定数据）。"
                ),
                "sections": [
                    _section(
                        "relations",
                        "按关系类型",
                        "合同三类关系的统计。",
                        [("relation", "关系类型")],
                        by_relation,
                    ),
                    _section(
                        "rules",
                        "按规则",
                        "各规则的统计。",
                        [("rule", "规则"), ("relation", "关系类型")],
                        by_rule,
                    ),
                    {
                        "key": "threshold",
                        "title": "置信度阈值扫描",
                        "summary": "置信度不低于阈值的岩性规则命中视为例外候选，不作为冲突报出。",
                        "columns": [
                            {"key": "threshold", "label": "阈值"},
                            {"key": "meets_target", "label": "两类关系均达标"},
                            {"key": "mean_f1", "label": "平均F1"},
                            *[
                                {"key": f"{key}_{metric}", "label": f"{name}{label}"}
                                for name, key in RELATION_KEYS.items()
                                if key != "structure"
                                for metric, label in (
                                    ("recall", "查全率"),
                                    ("precision", "查准率"),
                                )
                            ],
                        ],
                        "rows": scan,
                    },
                ],
            }
            with tempfile.TemporaryDirectory(prefix="geomanager-eval-") as directory:
                files = {}
                for key, rows in (
                    ("relations", by_relation),
                    ("rules", by_rule),
                    ("threshold", scan),
                ):
                    path = Path(directory) / f"{key}.csv"
                    _write_csv(path, rows)
                    files[key] = path
                try:
                    publish_validation(workflow, summary, files)
                except ComputeError as exc:
                    raise CommandError(str(exc)) from exc
        for row in by_relation:
            self.stdout.write(
                f"{row['relation']}: 真实{row['truth']} 报出{row['reported']} 正确{row['tp']} 误报{row['fp']} 漏检{row['fn']} 查全{row['recall']} 查准{row['precision']}"
            )
        self.stdout.write(
            f"建议阈值 report_conf_max={chosen['threshold']}，已登记为独立评价"
        )
