"""导出精确 Git 提交，生成可复现完整包、增量包和冻结清单。"""

from contextlib import contextmanager
from datetime import datetime, timezone
import fnmatch
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import time
import tomllib
import zipfile

if __package__:
    from . import server
else:
    import server

EXCLUDED_LINKS = {".claude", "CLAUDE.md"}
SCIENTIFIC_PATTERNS = (
    "examples/compute/*",
    "operators/*",
    "algorithms/*",
    "scientific/*",
    "backend/scripts/*",
    "scripts/*",
    "backend/apps/compute/*",
    "backend/apps/raster/*",
    "backend/apps/agent/*operator*",
    "backend/apps/business_flows/*operator*",
    "backend/apps/catalog/symbolization_templates.py",
)
FRONTEND_INPUTS = ("frontend/", "packages/", "pnpm-lock.yaml", "pnpm-workspace.yaml")
TOOL_FILES = (
    "server.py",
    "artifacts.py",
    "candidate.py",
    "candidate_support.py",
    "protocol.py",
)
BUILD_ENVIRONMENT = {
    "pnpm_config_verify_deps_before_run": "false",
    "pnpm_config_manage_package_manager_versions": "false",
    "pnpm_config_update_notifier": "false",
    "COREPACK_ENABLE_NETWORK": "0",
}


def git(repo, *args, binary=False):
    output = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    return output if binary else output.decode().strip()


def commit_id(repo, revision):
    return git(repo, "rev-parse", "--verify", revision + "^{commit}")


def is_ancestor(repo, base, commit):
    done = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base, commit], cwd=repo
    )
    server.require(done.returncode in (0, 1), "无法验证正式提交的祖先关系")
    return done.returncode == 0


def diff_summary(repo, base, commit):
    names = (
        git(
            repo, "diff", "--name-only", "--no-renames", "-z", base, commit, binary=True
        )
        .decode()
        .split("\0")
    )
    names = sorted(name for name in names if name)
    migrations = [
        name for name in names if "/migrations/" in name and name.endswith(".py")
    ]
    scientific = [
        name
        for name in names
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in SCIENTIFIC_PATTERNS)
    ]
    return {
        "baseCommit": base,
        "commit": commit,
        "paths": names,
        "topLevel": sorted({name.split("/", 1)[0] for name in names}),
        "migrations": migrations,
        "scientific": scientific,
        "scientificOperatorsUnchanged": not scientific,
        "frontendChanged": any(name.startswith(FRONTEND_INPUTS) for name in names),
        "ancestorVerified": is_ancestor(repo, base, commit),
    }


def fast_reasons(summary):
    reasons = []
    if summary["migrations"]:
        reasons.append("包含数据库迁移文件，请改用 full；正式 schema 门禁仍独立生效")
    if not summary["scientificOperatorsUnchanged"]:
        reasons.append("包含算子或科学计算脚本改动，请改用 full")
    if not summary["ancestorVerified"]:
        reasons.append("正式提交不是目标提交的祖先，请改用 full 进行独立候选验收")
    return reasons


def preflight(repo, commit, branch):
    server.require(
        not git(repo, "status", "--porcelain", "--untracked-files=no"),
        "已跟踪文件不干净，拒绝发布；不会自动提交或忽略并行修改",
    )
    server.require(
        git(repo, "branch", "--show-current") == branch, "当前不在固定个人分支"
    )
    server.require(commit == commit_id(repo, "HEAD"), "发布提交必须是当前个人分支 HEAD")
    return untracked_files(repo)


def untracked_files(repo):
    return sorted(
        os.fsdecode(name)
        for name in git(
            repo, "ls-files", "--others", "--exclude-standard", "-z", binary=True
        ).split(b"\0")
        if name
    )


def copy_build_resources(repo, root, names, source_files):
    resources = {}
    for name in names:
        server.safe_member(name)
        server.require(name not in source_files, "本机资源不可覆盖已冻结源码：" + name)
        destination = root / name
        server.require(
            destination.resolve().is_relative_to(root.resolve())
            and not name.startswith("frontend/dist/")
            and "node_modules" not in Path(name).parts,
            "本机资源目标路径无效：" + name,
        )
        source = repo / name
        server.require(source.is_file(), "缺少构建所需的本机资源：" + name)
        server.require(
            source.resolve().is_relative_to(repo.resolve()), "本机资源来源越界：" + name
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        resources[name] = {
            "sha256": server.sha(destination),
            "bytes": destination.stat().st_size,
        }
    return resources


@contextmanager
def elapsed(label, timings, emit=print):
    started = time.monotonic()
    emit(f"开始：{label}")
    try:
        yield
    finally:
        timings[label] = round(time.monotonic() - started, 3)
        emit(f"耗时：{label} {timings[label]:.3f} 秒")


def export(repo, commit, root):
    archive = root.parent / "source.tar"
    with archive.open("xb") as output:
        subprocess.run(["git", "archive", commit], cwd=repo, stdout=output, check=True)
    root.mkdir(mode=0o700)
    with tarfile.open(archive) as source:
        for member in source:
            if member.name in EXCLUDED_LINKS:
                server.require(member.issym(), "仅可排除已知开发说明符号链接")
                continue
            server.safe_member(member.name)
            server.require(
                member.isfile() or member.isdir(), "Git 导出中出现符号链接或特殊文件"
            )
            server.require(not member.mode & 0o6000, "Git 导出中出现特权权限")
            source.extract(member, root, filter="data")
    archive.unlink()


def git_files(repo, commit):
    raw = git(repo, "archive", commit, binary=True)
    result = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive:
            if member.name in EXCLUDED_LINKS:
                server.require(member.issym(), "开发说明排除项不是预期符号链接")
                continue
            server.safe_member(member.name)
            server.require(member.isfile() or member.isdir(), "基线 Git 中存在特殊文件")
            if member.isfile():
                content = archive.extractfile(member).read()
                result[member.name] = {
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "bytes": len(content),
                    "mode": server.extracted_file_mode(member.mode),
                }
    return result


def tree_files(root):
    files = {}
    for path in sorted(Path(root).rglob("*")):
        relative = path.relative_to(root).as_posix()
        server.safe_member(relative)
        server.require(not path.is_symlink(), "发布源码不能包含符号链接")
        if path.is_file():
            files[relative] = {
                "sha256": server.sha(path),
                "bytes": path.stat().st_size,
                "mode": server.extracted_file_mode(path.stat().st_mode),
            }
        else:
            server.require(path.is_dir(), "发布源码存在特殊文件")
    return files


def verified_baseline_files(repo, snapshot):
    files = {**git_files(repo, snapshot["commit"]), **snapshot["frontendFiles"]}
    server.require(
        snapshot.get("filesDigest") == server.digest(files),
        "正式 Git 源码与前端摘要不能还原上一发布清单，拒绝复用或切换",
    )
    return files


def write_package(files, read, output):
    with Path(output).open("xb") as destination:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=destination, mtime=0, compresslevel=6
        ) as zipped:
            with tarfile.open(
                fileobj=zipped, mode="w|", format=tarfile.PAX_FORMAT
            ) as archive:
                for name, expected in sorted(files.items()):
                    server.safe_member(name)
                    raw = read(name)
                    server.require(
                        len(raw) == expected["bytes"]
                        and hashlib.sha256(raw).hexdigest() == expected["sha256"],
                        "打包输入与文件清单不一致：" + name,
                    )
                    info = tarfile.TarInfo(name)
                    info.mode = expected["mode"]
                    info.mtime = 0
                    info.size = len(raw)
                    archive.addfile(info, io.BytesIO(raw))
    return {
        "file": Path(output).name,
        "sha256": server.sha(output),
        "bytes": Path(output).stat().st_size,
    }


def write_delta(files, known, read, output):
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as archive:
        for name, expected in sorted(files.items()):
            if known.get(name) != expected:
                archive.writestr(name, read(name))
        archive.writestr(
            "_file_manifest.json", json.dumps(files, ensure_ascii=False, sort_keys=True)
        )
    return {
        "file": Path(output).name,
        "sha256": server.sha(output),
        "bytes": Path(output).stat().st_size,
    }


def apply_delta(base, delta_path, output, limit):
    with zipfile.ZipFile(delta_path) as delta:
        names = delta.namelist()
        server.require(len(names) == len(set(names)), "增量包中有重复成员")
        server.require(
            sum(item.file_size for item in delta.infolist()) <= limit, "增量包展开过大"
        )
        for item in delta.infolist():
            server.safe_member(item.filename)
            server.require(
                (item.external_attr >> 16) & 0o170000
                not in (0o120000, 0o020000, 0o060000),
                "增量包包含链接或设备",
            )
        files = json.loads(delta.read("_file_manifest.json"))
        server.require(
            set(names) - {"_file_manifest.json"} <= set(files), "增量包包含清单外文件"
        )
        server.require(
            sum(item["bytes"] for item in files.values()) <= limit, "目标清单展开过大"
        )

        def read(name):
            server.safe_member(name)
            if name in names:
                return delta.read(name)
            path = Path(base) / name
            server.require(
                not Path(base).is_symlink() and not path.is_symlink(),
                "增量基线不可为符号链接",
            )
            server.require(
                path.resolve().is_relative_to(Path(base).resolve()), "增量基线越界"
            )
            server.require(
                not any(
                    parent.is_symlink()
                    for parent in path.parents
                    if parent != Path(base).parent
                ),
                "增量基线路径包含链接",
            )
            return path.read_bytes()

        return write_package(files, read, output)


def reuse_dist(package, root, expected, limit):
    files = server.archive_files(package, limit)
    frontend = {
        name: value
        for name, value in files.items()
        if name.startswith("frontend/dist/")
    }
    server.require(
        frontend and frontend == expected, "上一发布包前端摘要与正式快照不一致"
    )
    with tarfile.open(package) as archive:
        for member in archive:
            if member.name in frontend:
                archive.extract(member, root, filter="data")
    return frontend


def validate_frontend(root, files):
    index = Path(root) / "frontend/dist/index.html"
    server.require(index.is_file(), "缺少正式前端构建")
    entries = sorted(server.entry_scripts(index.read_text()))
    server.require(entries, "前端构建必须使用 /static/ 基址")
    for entry in entries:
        server.require(
            "frontend/dist/" + entry.split("?", 1)[0].removeprefix("/static/") in files,
            "首页脚本未包含在发布包中",
        )
    return entries


def package_source(
    repo,
    commit,
    base,
    work,
    config,
    summary,
    *,
    baseline_package=None,
    baseline_frontend=None,
    baseline_files=None,
    emit=print,
):
    root = work / "source"
    timings = {}
    build_resources = {}
    try:
        with elapsed("导出", timings, emit):
            export(repo, commit, root)
        with elapsed("前端构建或复用", timings, emit):
            if summary["frontendChanged"]:
                source_files = git_files(repo, commit)
                build_resources = copy_build_resources(
                    repo, root, config["local"]["buildResources"], source_files
                )
                server.write_json(work / "build-resources.json", build_resources)
                modules = repo / "frontend/node_modules"
                server.require(modules.is_dir(), "本机缺少前端依赖；工具不会自动安装")
                (root / "frontend/node_modules").symlink_to(
                    modules.resolve(), target_is_directory=True
                )
                try:
                    log = work / "build.log"
                    with log.open("wb") as output:
                        subprocess.run(
                            [*config["local"]["pnpm"], "run", "build:verify"],
                            cwd=root / "frontend",
                            stdout=output,
                            stderr=subprocess.STDOUT,
                            check=True,
                            timeout=config["local"]["buildSeconds"],
                            env={**os.environ, **BUILD_ENVIRONMENT},
                        )
                finally:
                    (root / "frontend/node_modules").unlink()
                for extra in (".cache",):
                    shutil.rmtree(root / "frontend" / extra, ignore_errors=True)
                for name in build_resources:
                    (root / name).unlink()
                for path in sorted(root.rglob("*"), reverse=True):
                    if (
                        path.is_file()
                        and not path.relative_to(root)
                        .as_posix()
                        .startswith("frontend/dist/")
                        and path.relative_to(root).as_posix() not in source_files
                    ):
                        path.unlink()
                for name, expected in source_files.items():
                    server.require(
                        server.sha(root / name) == expected["sha256"],
                        "正式构建修改了已冻结源码：" + name,
                    )
            else:
                server.require(
                    baseline_package is not None,
                    "复用前端需要上一发布包或只读下载的前端包",
                )
                reuse_dist(
                    baseline_package,
                    root,
                    baseline_frontend,
                    config["server"]["maxExpandedBytes"],
                )
        with elapsed("清单", timings, emit):
            files = tree_files(root)
            entries = validate_frontend(root, files)
            version = tomllib.loads((root / "backend/pyproject.toml").read_text())[
                "project"
            ]["version"]
            server.require(re.fullmatch(r"\d+\.\d+\.\d+", version), "应用版本格式错误")
            server.require(
                json.loads((root / "frontend/package.json").read_text())["version"]
                == version,
                "前后端版本不一致",
            )
            known = (
                dict(baseline_files)
                if baseline_files is not None
                else git_files(repo, base)
            )
            known.update(baseline_frontend or {})
        with elapsed("打包", timings, emit):

            def read(name):
                return (root / name).read_bytes()

            package = write_package(files, read, work / "release-code.tar.gz")
            delta = write_delta(files, known, read, work / "code-delta.zip")
            server.require(
                server.archive_files(
                    work / package["file"], config["server"]["maxExpandedBytes"]
                )
                == files,
                "完整包校验失败",
            )
            server.require(
                package["bytes"] <= config["server"]["maxArchiveBytes"], "完整包超限"
            )
        return {
            "commit": commit,
            "version": version,
            "package": package,
            "delta": delta,
            "files": files,
            "entryJavascript": entries,
            "frontendReused": not summary["frontendChanged"],
            "buildResources": build_resources,
            "timings": timings,
        }
    finally:
        server.write_json(work / "timings.json", timings)


def acceptance(artifact, checks):
    return {
        "accepted": True,
        "commit": artifact["commit"],
        "version": artifact["version"],
        "archiveSha256": artifact["package"]["sha256"],
        "checks": checks,
    }


def freeze(artifact, baseline, summary, config, mode, release_id):
    target = str(
        Path(config["server"]["releaseParent"])
        / f"geomanager-release-{artifact['version']}-{artifact['commit'][:7]}-{release_id}"
    )
    tools = Path(__file__).parent
    manifest = {
        "schema": 1,
        **artifact,
        "mode": mode,
        "releaseDir": target,
        "appRoot": target + "/code",
        "noSchemaChanges": not summary["migrations"],
        "scientificOperatorsUnchanged": summary["scientificOperatorsUnchanged"],
        "ancestorVerified": summary["ancestorVerified"],
        "releaseToolSha256": server.sha(tools / "server.py"),
        "toolHashes": {name: server.sha(tools / name) for name in TOOL_FILES},
        "baseline": baseline,
        "diff": summary,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    if mode == "fast":
        manifest["preflightAcceptance"] = acceptance(
            artifact,
            {
                "cleanTrackedWorktree": True,
                "originBranchVerified": True,
                "ancestorVerified": True,
                "noMigrationChanges": True,
                "scientificOperatorsUnchanged": True,
                "archiveVerified": True,
                "productionStaticBaseVerified": True,
            },
        )
    return manifest
