"""Independent evaluation stays immutable, authorized and outside model inputs."""

from copy import deepcopy
import json

import pytest
from django.contrib.auth.models import Permission

from apps.agent.models import AgentRun, RunEvent
from apps.agent.workflow_validation import publish_validation, validation_directory
from apps.catalog.models import DataResource
from apps.compute.models import ComputeTask
from apps.compute.packages import ComputeError, checksum
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo  # noqa: F401
from tests.integration.test_workflow_reports import completed  # noqa: F401


@pytest.fixture
def validation_input(completed):  # noqa: F811
    env = completed
    workflow = env["workflow"]
    workflow.plan["inputSnapshots"] = {
        role: DataResource.objects.get(pk=identity).updated_at.isoformat()
        for role, identity in workflow.plan["inputs"].items()
    }
    workflow.plan_hash = "a" * 64
    workflow.save(update_fields=["plan", "plan_hash"])
    directory = env["tmp"] / "independent-evaluation-source"
    directory.mkdir()
    files = {
        "report": ("检查评价.md", "# 独立评价\n已修正 2 处，正常区域保持不变。\n"),
        "statistics": ("修正统计.csv", "类别,修改数\n属性矛盾,2\n"),
        "metrics": ("评价指标.json", '{"corrected": 2, "unverified": null}\n'),
        "notes": ("评价范围.txt", "小范围演示案例，依据独立对照验收。\n"),
    }
    paths = {}
    for key, (name, content) in files.items():
        paths[key] = directory / name
        paths[key].write_text(content, encoding="utf-8")
    env.update(
        validation_files=paths,
        validation_summary={
            "scope": "小范围演示案例的独立评价",
            "summary": "两处获批修改已完成，正常区域未误改。",
            "sections": [
                {
                    "key": "changes",
                    "title": "修正结果",
                    "summary": "按当次输出重新统计。",
                    "columns": [
                        {"key": "name", "label": "检查项"},
                        {"key": "count", "label": "修改数"},
                        {"key": "verified", "label": "是否验证"},
                        {"key": "remaining", "label": "剩余问题"},
                    ],
                    "rows": [
                        {
                            "name": "属性一致性",
                            "count": 2,
                            "verified": True,
                            "remaining": 0,
                        },
                        {
                            "name": "其他地区",
                            "count": 0,
                            "verified": False,
                            "remaining": None,
                        },
                    ],
                }
            ],
        },
    )
    return env


@pytest.fixture
def published_validation(validation_input):
    env = validation_input
    publish_validation(
        env["workflow"], env["validation_summary"], env["validation_files"]
    )
    return env


def request(env, suffix="", *, project=None):
    return env["client"].get(
        f"/api/agent/workflows/{env['workflow'].id}/validation/{suffix}",
        HTTP_X_PROJECT_ID=str(project or env["project"].id),
    )


def stored_files(env):
    directory = validation_directory(env["workflow"])
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }


def test_missing_validation_explicit_and_does_not_generate_files(validation_input):
    env = validation_input
    before = (deepcopy(env["workflow"].plan), ComputeTask.objects.count())
    response = request(env)
    assert response.status_code == 200, response.content
    data = response.json()
    assert data["workflowId"] == str(env["workflow"].id)
    assert data["available"] is False and data["summary"]
    assert data["sections"] == [] and data["files"] == []
    assert stored_files(env) == {}
    assert request(env, "files/report/preview/").status_code == 404
    assert request(env, "files/report/download/").status_code == 404
    env["workflow"].refresh_from_db()
    assert (env["workflow"].plan, ComputeTask.objects.count()) == before


def test_validation_summary_preview_and_original_download(published_validation):
    env = published_validation
    response = request(env)
    assert response.status_code == 200, response.content
    data = response.json()
    assert data["available"] is True
    for key in ("scope", "summary", "sections"):
        assert data[key] == env["validation_summary"][key]
    records = {item["key"]: item for item in data["files"]}
    assert set(records) == set(env["validation_files"])
    for key, path in env["validation_files"].items():
        record = records[key]
        assert record["fileName"] == path.name
        assert record["checksum"] == checksum(path)
        assert record["sizeBytes"] == path.stat().st_size
        assert record["canDownload"] is True
        assert record["downloadUrl"].endswith(f"/files/{key}/download/")
        if key != "report":
            assert record["previewUrl"] is None
            assert request(env, f"files/{key}/preview/").status_code == 404
        download = request(env, f"files/{key}/download/")
        assert download.status_code == 200, download.content
        assert download["X-Content-Type-Options"] == "nosniff"
        assert download["Cache-Control"] == "private, no-store"
        assert "attachment;" in download["Content-Disposition"]
        assert b"".join(download.streaming_content) == path.read_bytes()
    preview = request(env, "files/report/preview/")
    assert preview.status_code == 200, preview.content
    assert preview.json()["content"] == env["validation_files"][
        "report"
    ].read_bytes().decode("utf-8")
    assert preview.json()["contentType"] == "text/markdown"
    assert preview.json()["truncated"] is False
    assert "SECRET_" not in json.dumps(data)


def test_markdown_preview_limit_is_explicit(validation_input):
    env = validation_input
    content = "中" * 200_001
    env["validation_files"]["report"].write_text(content, encoding="utf-8")
    publish_validation(
        env["workflow"], env["validation_summary"], env["validation_files"]
    )
    preview = request(env, "files/report/preview/")
    assert preview.status_code == 200, preview.content
    assert preview.json()["content"] == content[:200_000]
    assert preview.json()["truncated"] is True
    response = request(env, "files/report/download/")
    assert b"".join(response.streaming_content).decode("utf-8") == content


@pytest.mark.parametrize(
    "suffix", ["", "files/report/preview/", "files/statistics/download/"]
)
def test_owner_and_current_project_required(published_validation, suffix):
    env = published_validation
    env["client"].force_login(env["admin"])
    assert request(env, suffix).status_code == 404
    env["client"].force_login(env["owner"])
    assert request(env, suffix, project=1).status_code == 404


def test_export_permission_does_not_remove_read_access(published_validation):
    env = published_validation
    env["owner"].user_permissions.remove(
        Permission.objects.get(codename="export_dataresource")
    )
    response = request(env)
    assert response.status_code == 200, response.content
    assert all(item["canDownload"] is False for item in response.json()["files"])
    assert request(env, "files/report/preview/").status_code == 200
    assert request(env, "files/statistics/download/").status_code == 403


@pytest.mark.parametrize(
    "key", ["../escape", "bad/key", r"bad\key", "UPPER", "bad.key", ""]
)
def test_publisher_rejects_uncontrolled_file_keys(validation_input, key):
    env = validation_input
    with pytest.raises(ComputeError):
        publish_validation(
            env["workflow"],
            env["validation_summary"],
            {key: env["validation_files"]["report"]},
        )
    assert stored_files(env) == {}


def test_publisher_rejects_executable_files(validation_input):
    env = validation_input
    script = env["tmp"] / "evaluation.py"
    script.write_text("print('not a supported evaluation file')", encoding="utf-8")
    with pytest.raises(ComputeError):
        publish_validation(env["workflow"], env["validation_summary"], {"code": script})
    assert stored_files(env) == {}


def test_https_references_are_allowed_in_summary_and_markdown(validation_input):
    env = validation_input
    reference = "https://example.org/geology/rules#section-2"
    env["validation_summary"]["summary"] += " 来源：" + reference
    env["validation_files"]["report"].write_text(
        "# 独立评价\n依据 [制图规则](" + reference + ")。\n", encoding="utf-8"
    )
    publish_validation(
        env["workflow"], env["validation_summary"], env["validation_files"]
    )
    assert reference in request(env).json()["summary"]
    assert reference in request(env, "files/report/preview/").json()["content"]


@pytest.mark.parametrize(
    "path", [r"C:\private\reference.csv", "/root/private/reference.csv"]
)
@pytest.mark.parametrize("target", ["summary", "markdown"])
def test_private_absolute_paths_are_rejected(validation_input, path, target):
    env = validation_input
    if target == "summary":
        env["validation_summary"]["summary"] = "内部来源：" + path
    else:
        env["validation_files"]["report"].write_text(
            "# 内部来源\n" + path, encoding="utf-8"
        )
    with pytest.raises(ComputeError) as error:
        publish_validation(
            env["workflow"], env["validation_summary"], env["validation_files"]
        )
    assert error.value.status == 400
    assert stored_files(env) == {}


@pytest.mark.parametrize(
    "suffix",
    [
        "files/unknown/download/",
        "files/../report/preview/",
        "files/bad.key/download/",
        "files/%2E%2E%2Freport/preview/",
    ],
)
def test_http_rejects_unknown_keys_and_traversal(published_validation, suffix):
    assert request(published_validation, suffix).status_code == 404


def test_changed_evaluation_bytes_are_rejected_without_regeneration(
    published_validation,
):
    env = published_validation
    directory = validation_directory(env["workflow"])
    report = next(path for path in directory.rglob("*.md") if path.is_file())
    report.write_bytes(b"changed independent evaluation")
    for suffix in ("", "files/report/preview/", "files/report/download/"):
        assert request(env, suffix).status_code == 409
    assert report.read_bytes() == b"changed independent evaluation"


@pytest.mark.parametrize(
    "binding", ["plan_hash", "input_snapshots", "algorithm_version"]
)
def test_saved_validation_rejects_changed_execution_binding(
    published_validation, binding
):
    env = published_validation
    workflow = env["workflow"]
    if binding == "plan_hash":
        workflow.plan_hash = "f" * 64
        workflow.save(update_fields=["plan_hash"])
    elif binding == "input_snapshots":
        workflow.plan["inputSnapshots"]["early_image"] = "changed-input-revision"
        workflow.save(update_fields=["plan"])
    else:
        env["version"].checksum = "f" * 64
        env["version"].save(update_fields=["checksum"])
    for suffix in ("", "files/report/preview/", "files/statistics/download/"):
        assert request(env, suffix).status_code == 409


def test_republication_is_idempotent_and_conflicts_do_not_overwrite(
    published_validation,
):
    env = published_validation
    before, public = stored_files(env), request(env).json()
    publish_validation(
        env["workflow"],
        deepcopy(env["validation_summary"]),
        dict(env["validation_files"]),
    )
    assert stored_files(env) == before and request(env).json() == public
    changed = deepcopy(env["validation_summary"])
    changed["summary"] = "不同评价内容"
    with pytest.raises(ComputeError) as error:
        publish_validation(env["workflow"], changed, env["validation_files"])
    assert error.value.status == 409
    env["validation_files"]["report"].write_text("不同文件内容", encoding="utf-8")
    with pytest.raises(ComputeError) as error:
        publish_validation(
            env["workflow"], env["validation_summary"], env["validation_files"]
        )
    assert error.value.status == 409
    assert stored_files(env) == before and request(env).json() == public


def test_validation_publication_and_reads_do_not_add_execution_or_model_inputs(
    validation_input,
):
    env = validation_input
    workflow = env["workflow"]
    before_plan, before_hash = deepcopy(workflow.plan), workflow.plan_hash
    before = (
        workflow.steps.count(),
        ComputeTask.objects.count(),
        AgentRun.objects.count(),
        RunEvent.objects.count(),
        DataResource.objects.count(),
    )
    publish_validation(workflow, env["validation_summary"], env["validation_files"])
    assert request(env).status_code == 200
    assert request(env, "files/report/preview/").status_code == 200
    download = request(env, "files/statistics/download/")
    assert download.status_code == 200
    b"".join(download.streaming_content)
    workflow.refresh_from_db()
    assert workflow.plan == before_plan and workflow.plan_hash == before_hash
    assert (
        workflow.steps.count(),
        ComputeTask.objects.count(),
        AgentRun.objects.count(),
        RunEvent.objects.count(),
        DataResource.objects.count(),
    ) == before
