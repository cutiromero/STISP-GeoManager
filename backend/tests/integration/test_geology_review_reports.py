"""Short public reports bind actual CSV files, saved approval and expert sources."""

import csv

import pytest

from apps.agent.models import AgentWorkflow
from apps.agent.workflow import step
from apps.agent.workflow_reports import _paths
from apps.compute.models import (
    AlgorithmResource,
    AlgorithmVersion,
    ComputeInput,
    ComputeOutput,
    ComputeTask,
)
from apps.compute.packages import checksum
from apps.core.storage import app_path
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo  # noqa: F401
from tests.integration.test_workflow_reports import completed, request  # noqa: F401

pytestmark = pytest.mark.django_db


def output(env, task, key, rows):
    path = app_path(f"compute/geology-report/{task.id}/{key}.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(rows[0])
            if rows
            else ["feature_id", "kind", "status", "reason"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return ComputeOutput.objects.create(
        task=task,
        key=key,
        label=key,
        kind="table",
        file_name=key + ".csv",
        path=path.relative_to(env["tmp"] / "app").as_posix(),
        size_bytes=path.stat().st_size,
        checksum=checksum(path),
    )


@pytest.fixture
def geological(completed):  # noqa: F811
    env = completed
    workflow = env["workflow"]
    workflow.workflow_type = "geology_map_review"
    workflow.goal = "检查待提交的地质图，查阅专家知识并修正批准的问题"
    knowledge = workflow.evidence[0]
    knowledge.update(
        title="完整范围内部漏填规则",
        statement="范围完整且排除水体和未调查区时，唯一地质单元包围的空白可以填补。",
        conditions=["完整覆盖", "唯一图斑包围"],
        exceptions=["水体", "未调查区"],
        sources=[{"title": "项目整理规则", "locator": "第 1 条"}],
    )
    issues = [
        {
            "feature_id": "区域A",
            "kind": "fill_gap",
            "reason": "发现400平方米内部空白，由唯一图斑包围。",
            "status": "repairable",
            "rule_id": "coverage-rule",
            "area_m2": "400",
        }
    ]
    changes = [
        {
            **issues[0],
            "old_value": "未分类",
            "new_value": "0",
            "status": "applied",
            "current_label": "未分类空白",
            "suggested_label": "八宝山组（T3b）",
        }
    ]
    stats = [
        {
            "class": "0",
            "name": "八宝山组",
            "code": "T3b",
            "before_area_m2": 9600,
            "after_area_m2": 10000,
            "delta_area_m2": 400,
        },
        {
            "class": "8",
            "name": "八宝山组",
            "code": "T3b2",
            "before_area_m2": 10000,
            "after_area_m2": 10000,
            "delta_area_m2": 0,
        },
    ]
    stages, tasks = [], []
    for name, identifier in [
        ("check", "geology-map-check"),
        ("edit", "geology-map-correct"),
        ("recheck", "geology-map-check"),
    ]:
        algorithm, _ = AlgorithmResource.objects.get_or_create(
            identifier=identifier,
            project_tag=env["project"],
            defaults={
                "name": "地质成果检查" if name != "edit" else "地质成果受约束修正",
                "created_by": env["owner"],
            },
        )
        version, _ = AlgorithmVersion.objects.get_or_create(
            algorithm=algorithm,
            version="1.0.0",
            defaults={"status": "published", "checksum": "b" * 64},
        )
        task = ComputeTask.objects.create(
            owner=env["owner"],
            project_tag=env["project"],
            version=version,
            name="检查地质成果",
            status="succeeded",
            idempotency_key="report-" + name,
            request_hash="c" * 64,
        )
        ComputeInput.objects.create(task=task, key="features", resource=env["resource"])
        if name == "edit":
            output(env, task, "changes", changes)
            env["stats"] = output(env, task, "statistics", stats)
        else:
            result = output(env, task, "issues", issues if name == "check" else [])
            if name == "check":
                env["issues"] = result
        step(
            workflow, "submit_operator", compute_task_id=task.id, message="实际计算完成"
        )
        stages.append({"name": name, "identifier": identifier, "taskId": str(task.id)})
        tasks.append(task)
    review = {
        "proposalHash": "d" * 64,
        "suggestions": [
            {
                "id": "suggestion-a",
                "kind": "fill_gap",
                "featureId": "区域A",
                "title": "填补内部漏填",
                "currentState": "未分类空白",
                "suggestedState": "八宝山组（T3b）",
                "reason": "专家知识和唯一包围关系支持填补遗漏。",
                "ruleId": "coverage-rule",
                "areaM2": 400,
                "knowledgeRefs": [
                    {
                        "id": knowledge["id"],
                        "revision": knowledge["revision"],
                        "title": knowledge["title"],
                    }
                ],
            }
        ],
        "approvedSuggestionIds": ["suggestion-a"],
    }
    workflow.plan = {
        "stages": stages,
        "modificationReview": review,
        "finalDecision": {
            "resultSummary": "实际填补400平方米，内部空白已解决。",
            "judgement": "复核未发现本次规则范围内的剩余问题。",
            "uncertainties": [],
        },
        "hiddenAcceptance": "SECRET_INTERNAL_REFERENCE",
    }
    workflow.result_ids = list(
        ComputeOutput.objects.filter(task__in=tasks).values_list("id", flat=True)
    )
    workflow.save()
    step(
        workflow,
        "modifications_approved",
        action={
            "proposalHash": review["proposalHash"],
            "planHash": "e" * 64,
            "selectedSuggestionIds": ["suggestion-a"],
        },
        message="用户批准选中建议",
    )
    return env


def test_short_report_download_preview_and_exact_statistics(geological):
    env = geological
    response = request(env)
    assert response.status_code == 200, response.content
    assert response.json()["fileName"] == "检查报告.md"
    preview = request(env, "preview/", "get")
    content = preview.json()["content"]
    for expected in (
        "# 检查报告",
        "演示案例",
        "发现的问题",
        "专家知识提供的依据",
        "用户批准",
        "400.0 平方米",
        "涉及 1 个图斑",
        "剩余 0 处",
        "T3b2",
        "第 1 条",
    ):
        assert expected in content
    assert len(content) < 2000
    for private in (
        "SECRET_",
        "geometry_json",
        "input_checksum",
        "师弟",
        "精修图",
        "人工设错",
        "参考真值",
    ):
        assert private not in content
    downloaded = request(env, "download/", "get")
    assert b"".join(downloaded.streaming_content).decode("utf-8") == content
    imported = request(env, "import/")
    assert imported.status_code == 200 and imported.json()["resourceName"] == "检查报告"


@pytest.mark.parametrize(
    "mutation",
    [
        "no_approval",
        "approval_hash",
        "wrong_range",
        "missing_recheck",
        "no_final",
        "missing_knowledge",
    ],
)
def test_report_rejects_unbound_or_unfinished_story(geological, mutation):
    env = geological
    workflow = env["workflow"]
    if mutation == "no_approval":
        workflow.steps.filter(kind="modifications_approved").delete()
    elif mutation == "approval_hash":
        workflow.plan["modificationReview"]["proposalHash"] = "f" * 64
    elif mutation == "wrong_range":
        workflow.plan["modificationReview"]["suggestions"][0]["featureId"] = "区域B"
    elif mutation == "missing_recheck":
        workflow.plan["stages"] = workflow.plan["stages"][:-1]
    elif mutation == "no_final":
        workflow.plan.pop("finalDecision")
    elif mutation == "missing_knowledge":
        workflow.plan["modificationReview"]["suggestions"][0]["knowledgeRefs"] = []
    workflow.save()
    assert request(env).status_code == 409
    assert not _paths(workflow)[0].exists()


def test_report_actual_csv_corruption_and_area_disagreement_stop_generation(geological):
    env = geological
    path = app_path(env["stats"].path)
    content = path.read_text(encoding="utf-8-sig").replace(",400", ",500")
    path.write_text(content, encoding="utf-8")
    assert request(env).status_code == 409
    env["stats"].checksum = checksum(path)
    env["stats"].save()
    assert request(env).status_code == 409
    assert not _paths(env["workflow"])[0].exists()


def test_internal_preparation_terms_do_not_enter_public_report(geological):
    env = geological
    workflow = env["workflow"]
    workflow.goal = "师弟精修图的人工设错与参考真值检查"
    workflow.plan["finalDecision"]["judgement"] = "精修图作为案例资料"
    workflow.save()
    assert request(env).status_code == 200
    content = request(env, "preview/", "get").json()["content"]
    assert all(
        value not in content for value in ("师弟", "精修图", "人工设错", "参考真值")
    )


@pytest.mark.parametrize("status", ["cancelled", "failed", "waiting_approval"])
def test_rejected_or_unfinished_case_has_no_success_report(geological, status):
    env = geological
    AgentWorkflow.objects.filter(pk=env["workflow"].id).update(status=status)
    assert request(env).status_code == 409
    assert not _paths(env["workflow"])[0].exists()
