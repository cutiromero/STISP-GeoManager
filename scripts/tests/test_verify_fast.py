"""验证改动到命令的映射，不运行应用或修改主仓库 Git 状态。"""

from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_fast as fast


CONFIGURATION = "测试配置"
REPOSITORY = Path(__file__).resolve().parents[2]


def test_card_image_rules_always_run_without_card_changes(tmp_path):
    create(tmp_path, "frontend/scripts/check-card-images.mjs")
    steps, _ = fast.plan(tmp_path, [])
    assert ("node", "scripts/check-card-images.mjs") in commands(steps)
    assert ("node", "--test", "scripts/check-card-images.test.mjs") in commands(steps)


def create(root, path, text=""):
    destination = root / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")
    return destination


def commands(steps):
    return [step.command for step in steps]


def test_changed_files_include_staged_unstaged_untracked_and_unicode(
    monkeypatch, tmp_path
):
    seen = []

    def output(command, cwd):
        seen.append((command, cwd))
        return (
            "backend/apps/core/cli.py\0docs/中文 文档.md\0".encode()
            if "diff" in command
            else b"scripts/new.py\0backend/apps/core/cli.py\0"
        )

    monkeypatch.setattr(fast.subprocess, "check_output", output)
    assert fast.changed_files(tmp_path, "origin/main") == [
        "backend/apps/core/cli.py",
        "docs/中文 文档.md",
        "scripts/new.py",
    ]
    assert seen[0][0] == [
        "git",
        "diff",
        "--name-only",
        "--no-renames",
        "-z",
        "origin/main",
        "--",
    ]
    assert seen[1][0] == ["git", "ls-files", "--others", "--exclude-standard", "-z"]


def test_python_same_module_is_narrower_than_app_fallback(tmp_path):
    changed = "backend/apps/raster/services/color_mapping.py"
    create(tmp_path, changed)
    create(tmp_path, "backend/tests/unit/raster/test_color_mapping.py")
    create(tmp_path, "backend/tests/unit/raster/test_renderer_cache.py")
    steps, _ = fast.plan(tmp_path, [changed])
    assert len(steps) == 2
    assert steps[0].command == (fast.PYTHON, "-m", "ruff", "format", "--check", changed)
    assert "tests/unit/raster/test_color_mapping.py" in steps[1].command
    assert "tests/unit/raster/test_renderer_cache.py" not in steps[1].command
    assert "-m" not in steps[1].command[3:]


def test_override_and_app_prefixed_name(tmp_path):
    create(tmp_path, "backend/tests/integration/test_business_flow_review.py")
    create(tmp_path, "backend/tests/integration/test_business_flow_legacy.py")
    assert fast.backend_tests(
        tmp_path, "backend/apps/agent/business_flow_review.py"
    ) == {"tests/integration/test_business_flow_review.py"}
    assert fast.backend_tests(tmp_path, "backend/apps/business_flows/legacy.py") == {
        "tests/integration/test_business_flow_legacy.py"
    }


def test_same_module_can_live_outside_app_patterns(tmp_path):
    create(tmp_path, "backend/tests/unit/test_geology_review.py")
    assert fast.backend_tests(tmp_path, "backend/apps/agent/geology_review.py") == {
        "tests/unit/test_geology_review.py"
    }


@pytest.mark.parametrize(
    "reference",
    [
        "from apps.agent import views",
        "from apps.agent import tools, views as agent_views",
        "from apps.agent.views import workflow_json",
        "import apps.agent.views as agent_views",
        'patch("apps.agent.views.worker_online")',
        'monkeypatch.setattr("apps.agent.views.worker_online", lambda: True)',
        'import_module("apps.agent.views")',
        "from apps import agent as agent_app\nagent_app.views.workflow_json()",
        "apps.agent.views.workflow_json()",
        "def test_nested():\n    from apps.agent import views",
    ],
)
def test_static_module_references_narrow_generic_views(tmp_path, reference):
    create(tmp_path, "backend/tests/integration/test_agent_direct.py", reference)
    create(tmp_path, "backend/tests/integration/test_agent_other.py", "")
    assert fast.backend_tests(tmp_path, "backend/apps/agent/views.py") == {
        "tests/integration/test_agent_direct.py"
    }


@pytest.mark.parametrize(
    "reference",
    [
        "# from apps.agent import views",
        'reverse("agent:workflow-detail")',
        'client.get("/api/agent/workflows/")',
        "from apps.agent import views_extra",
        'patch("apps.agent.views_extra.worker_online")',
    ],
)
def test_non_module_references_do_not_narrow_tests(tmp_path, reference):
    create(tmp_path, "backend/tests/integration/test_agent_indirect.py", reference)
    create(tmp_path, "backend/tests/integration/test_agent_other.py", "")
    notices = []
    assert (
        len(fast.backend_tests(tmp_path, "backend/apps/agent/views.py", notices)) == 2
    )
    assert notices == [
        "backend/apps/agent/views.py：未找到直接相关测试，已退回应用级范围，共 2 个文件"
    ]


def test_same_name_precedes_static_references(tmp_path):
    create(tmp_path, "backend/tests/integration/test_agent_tools.py")
    create(
        tmp_path,
        "backend/tests/integration/test_agent_other.py",
        "from apps.agent.tools import execute",
    )
    assert fast.backend_tests(tmp_path, "backend/apps/agent/tools.py") == {
        "tests/integration/test_agent_tools.py"
    }


def test_static_references_stay_in_application_domain(tmp_path):
    create(
        tmp_path,
        "backend/tests/integration/test_agent_direct.py",
        "from apps.agent import views",
    )
    create(
        tmp_path,
        "backend/tests/integration/catalog/test_other.py",
        "from apps.agent import views",
    )
    assert fast.backend_tests(tmp_path, "backend/apps/agent/views.py") == {
        "tests/integration/test_agent_direct.py"
    }


def test_backend_limit_warns_at_plan_start_without_truncating(
    tmp_path, monkeypatch, capsys
):
    assert fast.BACKEND_TEST_FILE_WARNING_LIMIT == 15
    monkeypatch.setattr(fast, "BACKEND_TEST_FILE_WARNING_LIMIT", 1)
    for name in ("first", "second"):
        create(
            tmp_path,
            f"backend/tests/integration/test_agent_{name}.py",
            "from apps.agent import views",
        )
    monkeypatch.setattr(fast, "ROOT", tmp_path)
    monkeypatch.setattr(
        fast, "changed_files", lambda *args: ["backend/apps/agent/views.py"]
    )
    monkeypatch.setattr(sys, "argv", ["verify_fast.py", "--list"])
    assert fast.main() == 0
    output = capsys.readouterr().out
    assert output.startswith("!!! 后端测试范围提示：选中 2 个文件")
    assert "预计原因：直接静态引用" in output
    assert "test_agent_first.py" in output and "test_agent_second.py" in output


def test_large_fallback_explains_file_count_without_dropping_tests(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(fast, "BACKEND_TEST_FILE_WARNING_LIMIT", 1)
    create(tmp_path, "backend/tests/integration/test_agent_first.py")
    create(tmp_path, "backend/tests/integration/test_agent_second.py")
    notices = []
    steps, _ = fast.plan(tmp_path, ["backend/apps/agent/views.py"], notices=notices)
    assert "选中 2 个文件" in notices[0]
    assert "预计原因：部分模块未找到直接相关测试" in notices[0]
    assert "未找到直接相关测试，已退回应用级范围，共 2 个文件" in notices[1]
    assert len([part for part in steps[0].command if part.startswith("tests/")]) == 2


def test_generic_module_uses_app_tests_and_excludes_efficiency(tmp_path):
    changed = "backend/apps/core/models.py"
    create(tmp_path, changed)
    create(tmp_path, "backend/tests/integration/core/test_api.py")
    create(
        tmp_path,
        "backend/tests/unit/test_managed_file_evidence.py",
        "pytestmark = pytest.mark.efficiency\n",
    )
    steps, _ = fast.plan(tmp_path, [changed])
    assert steps[1].command[-2:] == ("-m", "not efficiency")
    assert "tests/unit/test_managed_file_evidence.py" not in steps[1].command


def test_changed_test_runs_itself_and_no_duplicate(tmp_path):
    changed = "backend/tests/unit/raster/test_color_mapping.py"
    create(tmp_path, changed)
    steps, _ = fast.plan(tmp_path, [changed, changed])
    assert steps[1].command.count("tests/unit/raster/test_color_mapping.py") == 1


def test_efficiency_only_test_without_sensitive_change_is_not_run(tmp_path):
    changed = "backend/tests/unit/core/test_sensitive.py"
    create(tmp_path, changed, "pytestmark = pytest.mark.efficiency\n")
    steps, _ = fast.plan(tmp_path, [changed])
    assert [step.name for step in steps] == ["Python 格式"]


@pytest.mark.parametrize(
    "path",
    [
        "backend/apps/compute/result_reads.py",
        "backend/apps/agent/run_stream.py",
        "backend/apps/compute/packages.py",
        "backend/apps/business_flows/input_preparation.py",
        "frontend/src/api/client.ts",
        "frontend/src/agent/AgentPage.tsx",
    ],
)
def test_efficiency_sensitive_paths(path):
    assert fast.needs_efficiency([path])


def test_text_and_simple_style_are_not_efficiency_sensitive():
    assert not fast.needs_efficiency(
        ["docs/example.md", "frontend/src/styles/login.css"]
    )


@pytest.mark.parametrize(
    "suffix, expected",
    [
        ("tsx", ["前端相关单元测试", "TypeScript 类型", "前端增量 lint"]),
        ("ts", ["前端相关单元测试", "TypeScript 类型", "前端增量 lint"]),
        ("css", ["前端相关单元测试", "前端增量 lint", "CSS 格式"]),
    ],
)
def test_frontend_steps(tmp_path, suffix, expected):
    changed = f"frontend/src/components/Example.{suffix}"
    create(tmp_path, changed)
    steps, _ = fast.plan(tmp_path, [changed])
    assert [step.name for step in steps] == expected
    assert "related" in steps[0].command
    assert "--run" in steps[0].command
    assert "src/components/Example." + suffix in steps[0].command
    assert "native" in steps[0].command
    assert not any("build" in part for command in commands(steps) for part in command)


def test_deleted_python_file_still_selects_tests_but_not_formatter(tmp_path):
    create(tmp_path, "backend/tests/unit/raster/test_color_mapping.py")
    steps, _ = fast.plan(tmp_path, ["backend/apps/raster/services/color_mapping.py"])
    assert [step.name for step in steps] == ["后端相关测试"]


def test_deleted_frontend_file_still_selects_related_but_not_lint(tmp_path):
    steps, _ = fast.plan(tmp_path, ["frontend/src/old.ts"])
    assert [step.name for step in steps] == ["前端相关单元测试", "TypeScript 类型"]


def test_browser_transitive_imports_default_to_suggestions(tmp_path):
    changed = "frontend/src/components/Example.tsx"
    create(tmp_path, changed)
    create(
        tmp_path,
        "frontend/src/components/barrel.ts",
        'export {default} from "./Example";',
    )
    create(
        tmp_path,
        "frontend/src/pages/Example.browser.test.tsx",
        'import "../components/barrel";',
    )
    create(tmp_path, "frontend/src/pages/Other.browser.test.tsx")
    steps, browsers = fast.plan(tmp_path, [changed])
    assert browsers == ["src/pages/Example.browser.test.tsx"]
    assert not any(step.name == "相关浏览器测试" for step in steps)
    browser_steps, _ = fast.plan(tmp_path, [changed], browser=True)
    assert browser_steps[-1].command == (
        "node",
        "scripts/run-browser-check.mjs",
        "src/pages/Example.browser.test.tsx",
    )


def test_global_style_includes_all_browser_files(tmp_path):
    create(tmp_path, "frontend/src/pages/Example.browser.test.tsx")
    _, browsers = fast.plan(tmp_path, ["frontend/src/styles.css"])
    assert browsers == ["src/pages/Example.browser.test.tsx"]


@pytest.mark.parametrize(
    "changed", ["docs/openapi.yaml", "mock/prism/examples/core.json"]
)
def test_contract_checks(changed, tmp_path):
    steps, _ = fast.plan(tmp_path, [changed])
    assert [step.name for step in steps] == ["check:api", "api:changes:check"]


def test_scripts_and_makefile_select_runner_tests(tmp_path):
    create(tmp_path, "scripts/verify_fast.py")
    create(tmp_path, "scripts/tests/test_verify_fast.py")
    steps, _ = fast.plan(tmp_path, ["scripts/verify_fast.py", "Makefile"])
    assert steps[1].command == (
        fast.PYTHON,
        "-m",
        "pytest",
        "scripts/tests/test_verify_fast.py",
        "-q",
    )


def test_no_verifiable_changes(tmp_path):
    assert fast.plan(
        tmp_path, ["docs/text.md", "image.png", "frontend/node_modules"]
    ) == ([], [])


def test_external_tool_is_not_treated_as_backend(tmp_path):
    create(tmp_path, "tools/example.py", "not finished Python")
    assert fast.plan(tmp_path, ["tools/example.py"]) == ([], [])


def test_unknown_app_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="缺少测试映射"):
        fast.plan(tmp_path, ["backend/apps/new_app/views.py"])


def test_every_real_application_has_existing_fallbacks():
    apps = {
        path.name
        for path in (REPOSITORY / "backend/apps").iterdir()
        if path.is_dir() and (path / "apps.py").is_file()
    }
    assert set(fast.BACKEND_TESTS) == apps
    for patterns in fast.BACKEND_TESTS.values():
        for pattern in patterns:
            assert fast.expand_tests(REPOSITORY / "backend/tests", (pattern,)), pattern
    for patterns in fast.BACKEND_OVERRIDES.values():
        for pattern in patterns:
            assert (REPOSITORY / "backend/tests" / pattern).is_file()
    for patterns in fast.BROWSER_TESTS.values():
        for pattern in patterns:
            assert fast.expand_tests(REPOSITORY / "frontend", (pattern,)), pattern


def test_run_steps_reports_failure_and_continues(monkeypatch, tmp_path, capsys):
    statuses = iter(
        [subprocess.CompletedProcess([], 1), subprocess.CompletedProcess([], 0)]
    )
    monkeypatch.setattr(fast.subprocess, "run", lambda *args, **kwargs: next(statuses))
    steps = [
        fast.Step("第一步", ".", ("example",), 1),
        fast.Step("第二步", ".", ("example",), 1),
    ]
    assert fast.run_steps(tmp_path, steps) == 1
    output = capsys.readouterr().out
    assert "第一步] 失败" in output
    assert "第二步] 通过" in output
    assert "耗时" in output


def test_main_list_never_executes(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["verify_fast.py", "--base", "main", "--list"])
    monkeypatch.setattr(fast, "changed_files", lambda root, base: ["docs/openapi.yaml"])
    monkeypatch.setattr(
        fast, "run_steps", lambda *args: pytest.fail("--list 不得执行检查")
    )
    assert fast.main() == 0
    assert "相对 main" in capsys.readouterr().out


def test_main_propagates_failed_step(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["verify_fast.py"])
    monkeypatch.setattr(fast, "changed_files", lambda *args: ["docs/openapi.yaml"])
    monkeypatch.setattr(fast, "run_steps", lambda *args: 1)
    assert fast.main() == 1
