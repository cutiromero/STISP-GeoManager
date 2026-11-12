"""按工作区改动选择本机快速检查；配置集中在下方。"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from fnmatch import fnmatchcase
import os
from pathlib import Path
import re
import shlex
import subprocess
import time


CONFIGURATION = "快速验证配置"
ROOT = Path(__file__).resolve().parents[1]
PYTHON = "/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin/python"
PNPM = (
    "pnpm",
    "--config.verify-deps-before-run=false",
    "--config.manage-package-manager-versions=false",
)
ENVIRONMENT = {"COREPACK_ENABLE_NETWORK": "0", "PYTHONDONTWRITEBYTECODE": "1"}
TIMEOUTS = {
    "format": 60,
    "pytest": 600,
    "unit": 300,
    "types": 300,
    "lint": 120,
    "contract": 300,
    "browser": 900,
}
BACKEND_TEST_FILE_WARNING_LIMIT = 15
BACKEND_TESTS = {
    "agent": (
        "unit/test_*workflow*.py",
        "unit/test_*model*.py",
        "integration/test_agent*.py",
        "integration/test_workflow*.py",
        "integration/test_logic*.py",
        "integration/test_demo*.py",
    ),
    "audit": ("integration/audit/test_*.py", "integration/test_audit*.py"),
    "business_flows": (
        "integration/test_business_flow*.py",
        "unit/test_input_adapters.py",
    ),
    "catalog": ("unit/catalog/test_*.py", "integration/catalog/test_*.py"),
    "compute": (
        "unit/compute/test_*.py",
        "unit/test_compute*.py",
        "integration/test_compute*.py",
        "unit/test_result_reads_efficiency.py",
    ),
    "content": (
        "unit/test_science_document.py",
        "integration/test_science*.py",
        "integration/test_project_content_upgrade.py",
    ),
    "core": (
        "unit/core/test_*.py",
        "integration/core/test_*.py",
        "unit/test_managed_file_evidence.py",
    ),
    "ecology": ("unit/test_ecology*.py", "integration/test_ecology*.py"),
    "knowledge": (
        "unit/test_weknora*.py",
        "integration/test_knowledge*.py",
        "integration/test_formal_rules.py",
    ),
    "omics": ("integration/omics/test_*.py",),
    "projects": (
        "integration/test_project*.py",
        "integration/test_public_project_navigation.py",
        "integration/test_upload_project_tags.py",
        "integration/test_provider_project_scope.py",
    ),
    "raster": ("unit/raster/test_*.py", "integration/raster/test_*.py"),
    "standards": ("integration/core/test_api.py", "integration/catalog/test_api.py"),
}
BACKEND_OVERRIDES = {
    "backend/apps/agent/budgets.py": (
        "integration/test_agent_budgets.py",
        "integration/test_workflow_model_policy.py",
        "integration/test_business_flow_budget_boundaries.py",
        "integration/test_business_flow_reasoning_effort.py",
    ),
    "backend/apps/agent/business_flow_context.py": (
        "integration/test_business_flow_context.py",
        "integration/test_business_flow_main_agent.py",
        "integration/test_logic_flow_budget_audit.py",
        "integration/test_logic_auxiliary_budget_audit.py",
        "unit/test_business_flow_resilience.py",
    ),
    "backend/apps/business_flows/runtime.py": (
        "integration/test_business_flow_runtime.py",
        "integration/test_business_flow_budget_boundaries.py",
        "integration/test_business_flow_main_agent.py",
        "integration/test_business_flow_reasoning_effort.py",
        "integration/test_business_flow_legacy.py",
        "integration/test_business_flow_input_bindings.py",
    ),
    "backend/apps/agent/input_script_model.py": (
        "integration/test_input_script_preparation_runtime.py",
        "integration/test_business_flow_context.py",
        "integration/test_business_flow_node_tools.py",
        "unit/test_business_flow_resilience.py",
    ),
    "backend/apps/business_flows/model_requests.py": (
        "integration/test_business_flow_budget_boundaries.py",
        "integration/test_business_flow_runtime.py",
        "integration/test_business_flow_main_agent.py",
        "integration/test_business_flow_node_tools.py",
        "integration/test_business_flow_context.py",
        "integration/test_input_script_preparation_runtime.py",
        "integration/test_logic_node_execution.py",
        "unit/test_business_flow_resilience.py",
    ),
    "backend/apps/business_flows/node_recovery.py": (
        "integration/test_business_flow_node_tools.py",
        "integration/test_business_flow_main_agent.py",
        "integration/test_logic_node_execution.py",
    ),
    "backend/apps/business_flows/script_preparation.py": (
        "integration/test_input_script_preparation_runtime.py",
        "integration/test_business_flow_node_tools.py",
        "integration/test_business_flow_context.py",
        "unit/test_business_flow_resilience.py",
    ),
    "backend/apps/agent/business_flow_actions.py": (
        "unit/test_business_flow_tool_protocol.py",
        "integration/test_business_flow_node_tools.py",
        "integration/test_business_flow_main_agent.py",
    ),
    "backend/apps/agent/business_flow_model.py": (
        "integration/test_business_flow_context.py",
        "integration/test_business_flow_execution.py",
        "integration/test_business_flow_review.py",
        "integration/test_business_flow_reasoning_effort.py",
        "integration/test_business_flow_node_trace.py",
        "integration/test_business_flow_main_agent.py",
        "integration/test_logic_flow_budget_audit.py",
    ),
    "backend/apps/business_flows/execution_session.py": (
        "unit/test_business_flow_main_agent.py",
        "integration/test_business_flow_main_agent.py",
        "integration/test_business_flow_node_trace.py",
    ),
    "backend/apps/business_flows/main_loop.py": (
        "unit/test_business_flow_main_agent.py",
        "integration/test_business_flow_main_agent.py",
        "integration/test_main_agent_ndvi.py",
        "integration/test_logic_node_execution.py",
    ),
    "backend/apps/compute/operator_checks.py": (
        "integration/test_compute_operator_protocol.py",
        "unit/test_compute_examples.py",
        "integration/test_main_agent_ndvi.py",
    ),
    "backend/apps/compute/templates.py": (
        "integration/test_compute.py",
        "integration/test_compute_operator_protocol.py",
        "integration/test_agent_compute_intent.py",
        "integration/test_agent_raster_metadata.py",
    ),
    "backend/apps/agent/business_flow_review.py": (
        "integration/test_business_flow_review.py",
        "integration/test_business_flow_budget_boundaries.py",
        "integration/test_business_flow_legacy.py",
    ),
    "backend/apps/business_flows/legacy.py": (
        "integration/test_business_flow_legacy.py",
    ),
    "backend/apps/business_flows/report_review.py": (
        "integration/test_business_flow_legacy.py",
    ),
}
BROWSER_TESTS = {
    "frontend/src/styles.css": ("src/**/*.browser.test.*",),
    "frontend/src/styles/*": (
        "src/pages/*.browser.test.*",
        "src/components/*.browser.test.*",
    ),
    "frontend/src/businessflows/*": ("src/businessflows/*.browser.test.*",),
    "frontend/src/admin/*": ("src/admin/AdminRoutes.browser.test.tsx",),
    "frontend/src/compute/*": ("src/compute/*.browser.test.*",),
    "frontend/src/knowledge/*": ("src/knowledge/*.browser.test.*",),
    "backend/apps/business_flows/*": ("src/businessflows/*.browser.test.*",),
    "backend/apps/agent/*": ("src/agent/*.browser.test.*",),
    "backend/apps/catalog/*": (
        "src/pages/DataCatalogPage.browser.test.tsx",
        "src/components/DataPanel.browser.test.tsx",
    ),
    "backend/apps/raster/*": (
        "src/components/RasterRenderingControls.browser.test.tsx",
    ),
    "backend/apps/compute/*": ("src/compute/*.browser.test.*",),
    "backend/apps/core/*": (
        "src/components/AccountAccess.browser.test.tsx",
        "src/admin/AdminRoutes.browser.test.tsx",
    ),
    "backend/apps/projects/*": ("src/projects/*.browser.test.*",),
    "backend/apps/knowledge/*": ("src/knowledge/*.browser.test.*",),
}
EFFICIENCY_PATHS = (
    "backend/apps/catalog/*",
    "backend/apps/raster/services/*",
    "backend/apps/raster/views.py",
    "backend/apps/compute/result_reads.py",
    "backend/apps/compute/packages.py",
    "backend/apps/compute/input_versions.py",
    "backend/apps/compute/services.py",
    "backend/apps/compute/worker.py",
    "backend/apps/compute/data.py",
    "backend/apps/core/file_evidence.py",
    "backend/apps/core/storage_locks.py",
    "backend/apps/core/heavy_work.py",
    "backend/apps/core/frontend_assets.py",
    "backend/apps/core/client_build.py",
    "backend/apps/agent/*context*.py",
    "backend/apps/agent/run_*.py",
    "backend/apps/agent/*history*.py",
    "backend/apps/agent/resource_*.py",
    "backend/apps/agent/workflow*.py",
    "backend/apps/agent/answer_preview.py",
    "backend/apps/agent/attachments.py",
    "backend/apps/agent/views.py",
    "backend/apps/agent/business_flow_review.py",
    "backend/apps/business_flows/*preparation.py",
    "backend/apps/business_flows/input_*.py",
    "backend/apps/business_flows/runtime.py",
    "backend/apps/business_flows/catalog.py",
    "backend/apps/business_flows/legacy.py",
    "frontend/src/api/*",
    "frontend/src/auth/*",
    "frontend/src/projects/*",
    "frontend/src/hooks/*",
    "frontend/src/map/*Query*",
    "frontend/src/map/*Preview*",
    "frontend/src/agent/*",
    "frontend/src/businessflows/*",
    "frontend/src/compute/*",
    "*efficiency*",
    "docs/efficiency-contracts.md",
)
SOURCE_SUFFIXES = (".ts", ".tsx", ".css")
PYTHON_ROOTS = ("backend/", "scripts/")
VITEST = ("exec", "vitest", "--config", "vitest.config.ts", "--configLoader", "native")
IMPORT_PATTERN = re.compile(r"(?:from\s*|import\s*(?:\(\s*)?)[\"'](\.[^\"']+)[\"']")
GENERIC_MODULES = {
    "__init__",
    "apps",
    "models",
    "views",
    "urls",
    "serializers",
    "conftest",
}


@dataclass(frozen=True)
class Step:
    name: str
    cwd: str
    command: tuple[str, ...]
    timeout: int

    def display(self) -> str:
        return f"cd {shlex.quote(self.cwd)} && {shlex.join(self.command)}"


def changed_files(root: Path, base: str = "HEAD") -> list[str]:
    commands = (
        ["git", "diff", "--name-only", "--no-renames", "-z", base, "--"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    )
    paths = set()
    for command in commands:
        output = subprocess.check_output(command, cwd=root)
        paths.update(os.fsdecode(path) for path in output.split(b"\0") if path)
    return sorted(paths)


def expand_tests(root: Path, patterns: tuple[str, ...]) -> set[str]:
    return {
        str(path.relative_to(root))
        for pattern in patterns
        for path in root.glob(pattern)
        if path.is_file()
    }


def needs_efficiency(paths: list[str]) -> bool:
    return any(
        fnmatchcase(path, pattern) for path in paths for pattern in EFFICIENCY_PATHS
    )


def references_module(path: Path, module: str) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return False
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported in node.names:
                if imported.name == module or imported.name.startswith(module + "."):
                    return True
                aliases[imported.asname or imported.name.split(".")[0]] = (
                    imported.name if imported.asname else imported.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            if node.module == module or node.module.startswith(module + "."):
                return True
            for imported in node.names:
                target = node.module + "." + imported.name
                if target == module:
                    return True
                aliases[imported.asname or imported.name] = target
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value == module or node.value.startswith(module + "."):
                return True
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        parts = []
        while isinstance(node, ast.Attribute):
            parts.insert(0, node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            target = ".".join([aliases.get(node.id, node.id), *parts])
            if target == module or target.startswith(module + "."):
                return True
    return False


def backend_tests(
    root: Path, changed: str, notices: list[str] | None = None
) -> set[str]:
    test_root = root / "backend/tests"
    path = Path(changed)
    if changed.startswith("backend/tests/"):
        if path.name.startswith("test_") and (root / path).is_file():
            return {str(path.relative_to("backend"))}
        patterns = (str(path.parent.relative_to("backend/tests") / "**/test_*.py"),)
    elif changed.startswith("backend/geomanager/"):
        patterns = ("unit/core/test_*.py", "integration/core/test_*.py")
    elif changed.startswith("backend/apps/"):
        app = path.parts[2]
        patterns = BACKEND_TESTS.get(app, ())
        if not patterns:
            raise ValueError(f"后端应用 {app} 缺少测试映射，请补充 BACKEND_TESTS")
        if changed in BACKEND_OVERRIDES:
            return {
                f"tests/{name}"
                for name in expand_tests(test_root, BACKEND_OVERRIDES[changed])
            }
        domain = expand_tests(test_root, patterns)
        if path.stem not in GENERIC_MODULES and "migrations" not in path.parts:
            names = {
                f"test_{path.stem}.py",
                f"test_{app}_{path.stem}.py",
                f"test_{app.rstrip('s')}_{path.stem}.py",
            }
            exact = {name for name in domain if Path(name).name in names}
            if not exact:
                exact = {
                    str(candidate.relative_to(test_root))
                    for name in names
                    for candidate in test_root.rglob(name)
                }
            if exact:
                return {f"tests/{name}" for name in exact}
        module = ".".join(path.with_suffix("").parts[1:])
        direct = {
            name for name in domain if references_module(test_root / name, module)
        }
        if direct:
            return {f"tests/{name}" for name in direct}
        if notices is not None:
            notices.append(
                f"{changed}：未找到直接相关测试，已退回应用级范围，共 {len(domain)} 个文件"
            )
        return {f"tests/{name}" for name in domain}
    else:
        return set()
    selected = expand_tests(test_root, BACKEND_OVERRIDES.get(changed, patterns))
    return {f"tests/{name}" for name in selected}


def efficiency_only(path: Path) -> bool:
    return bool(
        re.search(
            r"^pytestmark\s*=\s*pytest\.mark\.efficiency\b", path.read_text(), re.M
        )
    )


def related_browser_tests(root: Path, changed: list[str]) -> list[str]:
    frontend = root / "frontend"
    files = [
        path
        for path in (frontend / "src").rglob("*")
        if path.suffix in SOURCE_SUFFIXES
        and path.is_file()
        and "generated" not in path.parts
    ]
    reverse: dict[str, set[str]] = {}
    for source in files:
        for target in IMPORT_PATTERN.findall(source.read_text(encoding="utf-8")):
            base = source.parent / target
            candidates = [
                base,
                *(Path(str(base) + suffix) for suffix in SOURCE_SUFFIXES),
                *(base / ("index" + suffix) for suffix in SOURCE_SUFFIXES),
            ]
            for candidate in candidates:
                normalized = (
                    str(candidate.resolve().relative_to(root))
                    if candidate.resolve().is_relative_to(root)
                    else ""
                )
                if candidate.is_file() or normalized in changed:
                    reverse.setdefault(normalized, set()).add(
                        str(source.relative_to(root))
                    )
                    break
    affected = set(changed)
    pending = list(changed)
    while pending:
        for importer in reverse.get(pending.pop(), ()):
            if importer not in affected:
                affected.add(importer)
                pending.append(importer)
    selected = {
        str(Path(path).relative_to("frontend"))
        for path in affected
        if ".browser.test." in path and (root / path).is_file()
    }
    for pattern, tests in BROWSER_TESTS.items():
        if any(fnmatchcase(path, pattern) for path in changed):
            selected.update(expand_tests(frontend, tests))
    return sorted(selected)


def plan(
    root: Path,
    paths: list[str],
    browser: bool = False,
    notices: list[str] | None = None,
) -> tuple[list[Step], list[str]]:
    steps = []
    selection_notices = []

    def add(name: str, cwd: str, command: tuple[str, ...], kind: str) -> None:
        steps.append(Step(name, cwd, command, TIMEOUTS[kind]))

    if (root / "frontend/scripts/check-card-images.mjs").is_file():
        add(
            "卡片图片规则",
            "frontend",
            ("node", "scripts/check-card-images.mjs"),
            "lint",
        )
        add(
            "卡片图片规则回归",
            "frontend",
            ("node", "--test", "scripts/check-card-images.test.mjs"),
            "unit",
        )

    python_files = [
        path
        for path in paths
        if path.startswith(PYTHON_ROOTS)
        and path.endswith(".py")
        and (root / path).is_file()
    ]
    if python_files:
        add(
            "Python 格式",
            ".",
            (PYTHON, "-m", "ruff", "format", "--check", *python_files),
            "format",
        )
    tests = set()
    for path in paths:
        if path.startswith("backend/") and path.endswith(".py"):
            tests.update(backend_tests(root, path, selection_notices))
    efficiency = needs_efficiency(paths)
    if not efficiency:
        tests = {path for path in tests if not efficiency_only(root / "backend" / path)}
    if notices is not None:
        if len(tests) > BACKEND_TEST_FILE_WARNING_LIMIT:
            reason = (
                "部分模块未找到直接相关测试，已回退应用级范围"
                if selection_notices
                else "直接静态引用、同名测试或显式映射的相关文件较多，取并集后范围较大"
            )
            notices.append(
                f"!!! 后端测试范围提示：选中 {len(tests)} 个文件，超过配置上限 "
                f"{BACKEND_TEST_FILE_WARNING_LIMIT}；预计原因：{reason}；仍照常运行。"
            )
        notices.extend(selection_notices)
    if tests:
        marker = () if efficiency else ("-m", "not efficiency")
        add(
            "后端相关测试",
            "backend",
            (PYTHON, "-m", "pytest", *sorted(tests), "-q", *marker),
            "pytest",
        )
    script_tests = {
        path
        for path in paths
        if path.startswith("scripts/tests/test_")
        and path.endswith(".py")
        and (root / path).is_file()
    }
    for path in python_files:
        if path.startswith("scripts/") and not path.startswith("scripts/tests/"):
            candidate = f"scripts/tests/test_{Path(path).stem}.py"
            if (root / candidate).is_file():
                script_tests.add(candidate)
    if "Makefile" in paths and (root / "scripts/tests/test_verify_fast.py").is_file():
        script_tests.add("scripts/tests/test_verify_fast.py")
    if script_tests:
        add(
            "脚本相关测试",
            ".",
            (PYTHON, "-m", "pytest", *sorted(script_tests), "-q"),
            "pytest",
        )
    frontend_files = [
        str(Path(path).relative_to("frontend"))
        for path in paths
        if path.startswith("frontend/") and Path(path).suffix in SOURCE_SUFFIXES
    ]
    if frontend_files:
        add(
            "前端相关单元测试",
            "frontend",
            (*PNPM, *VITEST, "related", *frontend_files, "--run", "--passWithNoTests"),
            "unit",
        )
        if any(Path(path).suffix in (".ts", ".tsx") for path in frontend_files):
            add("TypeScript 类型", "frontend", (*PNPM, "run", "typecheck"), "types")
        existing = [
            path for path in frontend_files if (root / "frontend" / path).is_file()
        ]
        if existing:
            add(
                "前端增量 lint",
                "frontend",
                (*PNPM, "exec", "oxlint", *existing, "--no-error-on-unmatched-pattern"),
                "lint",
            )
        styles = [path for path in existing if path.endswith(".css")]
        if styles:
            add(
                "CSS 格式",
                "frontend",
                (*PNPM, "exec", "oxfmt", *styles, "--check"),
                "format",
            )
    if any(
        path == "docs/openapi.yaml" or path.startswith("mock/prism/examples/")
        for path in paths
    ):
        for script in ("check:api", "api:changes:check"):
            add(script, "frontend", (*PNPM, "run", script), "contract")
    browsers = (
        related_browser_tests(root, paths)
        if any(path.startswith(("frontend/", "backend/apps/")) for path in paths)
        else []
    )
    if browser and browsers:
        add(
            "相关浏览器测试",
            "frontend",
            ("node", "scripts/run-browser-check.mjs", *browsers),
            "browser",
        )
    return steps, browsers


def run_steps(root: Path, steps: list[Step]) -> int:
    failures = 0
    environment = dict(os.environ, **ENVIRONMENT)
    for step in steps:
        print(f"\n[{step.name}] {step.display()}", flush=True)
        started = time.monotonic()
        try:
            status = subprocess.run(
                step.command, cwd=root / step.cwd, env=environment, timeout=step.timeout
            ).returncode
        except subprocess.TimeoutExpired:
            status = 124
            print(f"超时：{step.timeout} 秒", flush=True)
        except OSError as error:
            status = 127
            print(f"无法执行：{error}", flush=True)
        failures += status != 0
        print(
            f"[{step.name}] {'通过' if status == 0 else '失败'}，"
            f"退出码 {status}，耗时 {time.monotonic() - started:.2f}s",
            flush=True,
        )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="HEAD", help="比较基准，默认 HEAD")
    parser.add_argument("--browser", action="store_true", help="执行相关浏览器测试")
    parser.add_argument("--list", action="store_true", help="仅显示检查计划")
    args = parser.parse_args()
    started = time.monotonic()
    notices = []
    try:
        paths = changed_files(ROOT, args.base)
        steps, browsers = plan(ROOT, paths, args.browser, notices)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"生成检查计划失败：{error}")
        return 1
    for notice in notices:
        print(notice, flush=True)
    print(
        f"相对 {args.base} 的改动：{len(paths)} 个文件；快速检查：{len(steps)} 步",
        flush=True,
    )
    uncovered = [
        path
        for path in paths
        if path.endswith(".py") and not path.startswith(PYTHON_ROOTS)
    ]
    if uncovered:
        print(
            "未自动覆盖的 Python 工具（须走所属工具的独立验证）："
            + "、".join(uncovered),
            flush=True,
        )
    failures = 0
    if args.list:
        for step in steps:
            print(f"[{step.name}] {step.display()}（超时 {step.timeout}s）")
    elif steps:
        failures = run_steps(ROOT, steps)
    else:
        print("没有可验证的改动。文档、图片等不触发构建或测试。")
    if browsers:
        print(
            "\n相关浏览器测试"
            + ("（已纳入执行）" if args.browser else "（默认不运行）")
            + "："
        )
        for path in browsers:
            print(f"  {path}")
        print(
            "完整命令：cd frontend && "
            + shlex.join(("node", "scripts/run-browser-check.mjs", *browsers))
        )
    print(
        f"\n汇总：{'计划' if args.list else '执行'} {len(steps)} 步，失败 {failures} 步，"
        f"总耗时 {time.monotonic() - started:.2f}s"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
