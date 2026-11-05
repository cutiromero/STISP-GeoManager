"""Short public reports bind actual CSV files, saved approval and expert sources."""

import csv
import copy

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
from apps.knowledge.models import KnowledgeEntry
from apps.knowledge.services import serialize
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo  # noqa: F401
from tests.integration.test_workflow_reports import completed, request  # noqa: F401

pytestmark = pytest.mark.django_db


def test_report_reads_large_actual_change_table_without_old_256k_limit(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from apps.agent.geology_review_report import actual_table

    path = tmp_path / "changes.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["group_id", "action", "reason"])
        writer.writeheader()
        writer.writerows(
            {
                "group_id": f"AG-{index}",
                "action": "downweight",
                "reason": "获批范围内确定性处理，原始资料保留" * 3,
            }
            for index in range(7385)
        )
    assert path.stat().st_size > 256 * 1024
    output = SimpleNamespace(expired=False, path="changes.csv", checksum=checksum(path))
    task = SimpleNamespace(
        outputs=SimpleNamespace(
            filter=lambda **kwargs: SimpleNamespace(first=lambda: output)
        )
    )
    monkeypatch.setattr("apps.agent.geology_review_report.app_path", lambda _: path)
    assert len(actual_table(task, "changes")) == 7385


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


def replace_rows(result, rows):
    path = app_path(result.path)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result.checksum, result.size_bytes = checksum(path), path.stat().st_size
    result.save(update_fields=["checksum", "size_bytes"])


def read_rows(result):
    with app_path(result.path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_report_each_change_names_its_own_knowledge_rule_and_actual_algorithm(
    geological,
):
    env, workflow = geological, geological["workflow"]
    entry = KnowledgeEntry.objects.create(
        project_tag=env["project"],
        seed_key="report-age",
        title="八宝山组时代定义",
        statement="采用该条目定义的地层属于晚三叠世。",
        status="published",
        revision=3,
        sources=[{"title": "中国岩石地层名称辞典", "locator": "06-63-0717"}],
    )
    evidence = serialize(entry)
    workflow.evidence.append(evidence)
    review = workflow.plan["modificationReview"]
    suggestion = copy.deepcopy(review["suggestions"][0])
    suggestion.update(
        id="suggestion-b",
        kind="set_age",
        featureId="区域B",
        title="更新地层时代",
        currentState="晚侏罗世",
        suggestedState="晚三叠世",
        ruleId="age-rule",
        areaM2=100,
        reason="地层时代与适用辞书定义矛盾。",
        knowledgeRefs=[
            {"id": entry.id, "revision": entry.revision, "title": entry.title}
        ],
    )
    review["suggestions"].append(suggestion)
    review["approvedSuggestionIds"].append(suggestion["id"])
    approval = workflow.steps.get(kind="modifications_approved")
    approval.action["selectedSuggestionIds"] = review["approvedSuggestionIds"]
    approval.save(update_fields=["action"])
    workflow.plan["algorithms"] = {
        "geology-map-correct": {
            "name": "未执行的伪造工具",
            "manifest": {"version": "99.0"},
        }
    }
    workflow.save()
    issues = read_rows(env["issues"])
    issues.append(
        {
            **issues[0],
            "feature_id": "区域B",
            "kind": "set_age",
            "rule_id": "age-rule",
            "area_m2": "100",
        }
    )
    replace_rows(env["issues"], issues)
    edit = ComputeTask.objects.get(pk=workflow.plan["stages"][1]["taskId"])
    changes = edit.outputs.get(key="changes")
    rows = read_rows(changes)
    rows.append(
        {
            **rows[0],
            "feature_id": "区域B",
            "kind": "set_age",
            "rule_id": "age-rule",
            "area_m2": "100",
            "old_value": "J3",
            "new_value": "T3",
            "current_label": "晚侏罗世",
            "suggested_label": "晚三叠世",
        }
    )
    replace_rows(changes, rows)
    assert request(env).status_code == 200
    content = request(env, "preview/", "get").json()["content"]
    assert "未执行的伪造工具" not in content and "99.0" not in content
    for heading, end in (
        ("## 用户批准的建议修改", "## 算法实际修改了什么"),
        ("## 算法实际修改了什么", "### 修改前后面积"),
    ):
        section = content.split(heading)[1].split(end)[0]
        first, second = section.split("- 图斑 区域A：")[1].split("- 图斑 区域B：")
        assert "完整范围内部漏填规则" in first and "第 1 条" in first
        assert "coverage-rule" in first and "八宝山组时代定义" not in first
        assert "八宝山组时代定义" in second and "修订 3" in second
        assert "06-63-0717" in second and "age-rule" in second
        assert "完整范围内部漏填规则" not in second
        assert all("地质成果受约束修正 1.0.0" in item for item in (first, second))


def inspection_case(env, kind, *, repairable=False):
    workflow = env["workflow"]
    stages = workflow.plan["stages"]
    check_id = stages[0]["taskId"]
    for stage in stages[1:]:
        workflow.steps.filter(compute_task_id=stage["taskId"]).delete()
        task = ComputeTask.objects.get(pk=stage["taskId"])
        task.outputs.all().delete()
        task.delete()
        stage.pop("taskId")
        stage["status"] = "skipped"
    workflow.plan.pop("modificationReview")
    workflow.steps.filter(kind="modifications_approved").delete()
    workflow.plan["reviewOutcome"] = {"kind": kind, "checkTaskId": check_id}
    workflow.plan["finalDecision"].update(
        judgement="现有证据支持检查结论，未执行地图修改。",
        resultSummary="请根据检查结果决定是否补充资料。",
    )
    check = ComputeTask.objects.get(pk=check_id)
    stats = read_rows(env["stats"])
    for row in stats:
        row.update(after_area_m2=row["before_area_m2"], delta_area_m2=0)
    env["stats"] = output(env, check, "statistics", stats)
    if kind == "requires_evidence" or repairable:
        rows = read_rows(env["issues"])
        rows[0].update(
            status="repairable" if repairable else "needs_review",
            reason="尚未确认空白是否属于未调查区，需要补充覆盖资料。",
        )
        replace_rows(env["issues"], rows)
    else:
        path = app_path(env["issues"].path)
        path.write_text("feature_id,kind,status,reason\n", encoding="utf-8")
        env["issues"].checksum = checksum(path)
        env["issues"].save(update_fields=["checksum"])
    workflow.result_ids = list(check.outputs.values_list("id", flat=True))
    workflow.save()
    return workflow


@pytest.mark.parametrize(
    "kind,label", [("no_changes", "无需修改"), ("requires_evidence", "需要补充证据")]
)
def test_inspection_only_report_uses_real_check_and_never_claims_edit_or_recheck(
    geological, kind, label
):
    env = geological
    inspection_case(env, kind)
    response = request(env)
    assert response.status_code == 200, response.content
    content = request(env, "preview/", "get").json()["content"]
    assert label in content and "未执行修正及修正后复核" in content
    assert "完整范围内部漏填规则" in content and "第 1 条" in content
    assert "检查算法：地质成果检查 1.0.0" in content
    assert "地质成果受约束修正" not in content and "修正算法：" not in content
    assert "算法实际修改了什么" not in content


def test_inspection_only_report_cannot_hide_repairable_issue(geological):
    inspection_case(geological, "no_changes", repairable=True)
    assert request(geological).status_code == 409
    assert not _paths(geological["workflow"])[0].exists()
