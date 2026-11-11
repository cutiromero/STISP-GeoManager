"""服务器端协议：只读观测、校验接收、独立会话、状态和显式回退。"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import tomllib

if __package__:
    from . import artifacts, candidate, development, server
else:
    import artifacts
    import candidate
    import development
    import server

TERMINAL = (
    "production-accepted.json",
    "production-rolled-back.json",
    "manual-intervention-required.json",
)


def bind(config):
    value = dict(config)
    raw = tomllib.loads(Path(value["productionConfig"]).read_text())
    development_enabled = (
        raw.get("application", {}).get("development", {}).get("enabled", False)
    )
    server.require(
        not development_enabled or value.get("developmentMode", False),
        "运行环境已启用开发存储规则，发布配置必须设置 server.developmentMode=true",
    )
    storage = raw["application"]["storage"]
    server.require(
        storage["app_data"] == value["appData"]
        and storage["research_data_root"] == value["researchData"],
        "正式数据目录与配置身份不一致",
    )
    server.require(value["deployLock"] != value["publishLock"], "发布锁不得相同")
    server.require(
        value["baseUrl"] == "http://127.0.0.1:6007", "正式检查仅允许本机 6007"
    )
    value["expectedPreviousRoot"] = server.launcher_root(value)
    value["expectedLauncherSha256"] = server.sha(value["launcher"])
    text = Path(value["launcher"]).read_text()
    worker = re.findall(r"^WORKER_APP_ROOT=(\S+)\s*$", text, re.MULTILINE)
    server.require(len(worker) == 1, "启动器必须恰有一个 WORKER_APP_ROOT")
    value["expectedRoleRoots"] = {role: worker[0] for role in server.ROLES[1:]}
    static = Path(value["appData"]) / "static"
    if static.is_symlink():
        value["expectedStaticLinkTarget"] = str(static.resolve())
    return value


def frontend_files(root):
    directory = Path(root) / "frontend/dist"
    server.require(
        directory.is_dir() and not directory.is_symlink(), "正式前端目录无效"
    )
    return {
        "frontend/dist/" + name: item
        for name, item in artifacts.tree_files(directory).items()
    }


def process_status(config, root):
    roles = {role: [] for role in server.ROLES}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            item = server.process(entry.name)
            role = server.role_of(item, config, root)
            if role:
                roles[role].append(item)
        except (OSError, ProcessLookupError):
            continue
    return {
        role: {
            "status": "running"
            if len(items) == 1
            else "missing"
            if not items
            else "ambiguous",
            "processes": items,
        }
        for role, items in roles.items()
    }


def describe(config, *, strict=True):
    config = bind(config)
    try:
        snapshot = server.inspect(config)
    except (server.ReleaseError, OSError) as error:
        if strict:
            raise
        root = server.launcher_root(config)
        snapshot = {
            "schema": 1,
            "observedAt": datetime.now(timezone.utc).isoformat(),
            "appRoot": root,
            "launcherSha256": server.sha(config["launcher"]),
            "baselineVerified": False,
            "observationError": type(error).__name__,
            "processStatus": process_status(config, root),
            "active": server.active_counts(config),
        }
    else:
        snapshot["baselineVerified"] = True
        snapshot["processStatus"] = {
            role: {"status": "running", "processes": [item]}
            for role, item in snapshot["processes"].items()
        }
    root = Path(snapshot["appRoot"])
    identity = root.parent / "staged.json"
    if strict:
        server.require(
            identity.is_file(),
            "正式目录缺少 staged.json，不能猜测正式提交；需人工补全历史证据",
        )
    staged = json.loads(identity.read_text()) if identity.is_file() else {}
    commit = staged.get("commit")
    if strict:
        server.require(re.fullmatch(r"[a-f0-9]{40}", commit or ""), "正式提交身份无效")
    version = tomllib.loads((root / "backend/pyproject.toml").read_text())["project"][
        "version"
    ]
    groups = {}
    with server.readonly_db(config) as database:
        for table, statuses in server.ACTIVE.items():
            placeholders = ",".join("?" for _ in statuses)
            counts = dict(
                database.execute(
                    f'SELECT status, COUNT(*) FROM "{table}" WHERE status IN ({placeholders}) GROUP BY status',
                    statuses,
                )
            )
            groups[table] = {status: counts.get(status, 0) for status in statuses}
    snapshot.update(
        {
            "commit": commit,
            "filesDigest": staged.get("filesDigest"),
            "version": version,
            "diskFreeBytes": shutil.disk_usage(config["releaseParent"]).free,
            "taskCounts": groups,
            "locks": {
                "deployExists": Path(config["deployLock"]).exists(),
                "publishOwners": server.lock_owner(config["publishLock"])
                if Path(config["publishLock"]).exists()
                else [],
            },
            "frontendFiles": frontend_files(root),
            "roleRoots": config["expectedRoleRoots"],
            "rollbackAvailable": not config.get("developmentMode", False)
            and (root.parent / "rollback-context.json").is_file(),
            "codeRecoveryPolicy": "rebuild_from_git"
            if config.get("developmentMode", False)
            else "stored_release",
        }
    )
    return snapshot


def stream_frontend(config, expected):
    current = describe(config)
    for key in ("appRoot", "launcherSha256", "frontendFiles"):
        server.require(current[key] == expected[key], "下载复用前端时正式身份变化")
    with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz") as archive:
        for name in sorted(current["frontendFiles"]):
            path = Path(current["appRoot"]) / name
            archive.add(path, arcname=name, recursive=False)


def operations_path(config, path):
    value = Path(path)
    parent = Path(config["opsParent"])
    server.require(
        value.parent == parent
        and re.fullmatch(r"[0-9TZ-]+-[a-f0-9]{7}-[a-f0-9]{6}", value.name),
        "发布操作目录越界",
    )
    server.require(
        not parent.is_symlink() and not value.is_symlink(), "操作目录不能为符号链接"
    )
    return value


def create_operations(config, path):
    root = operations_path(config, path)
    root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.mkdir(mode=0o700)
    return {"created": True, "operations": str(root)}


def verify_inputs(ops, fingerprint, config, *, verify_package=True):
    path = ops / "frozen-manifest.json"
    server.require(
        re.fullmatch(r"[a-f0-9]{64}", fingerprint or "")
        and server.sha(path) == fingerprint,
        "清单 SHA-256 不匹配",
    )
    release = json.loads(path.read_text())
    server.require(
        re.fullmatch(r"[a-f0-9]{40}", release.get("commit", "")), "提交身份错误"
    )
    server.require(
        release["releaseToolSha256"]
        == server.sha(Path(__file__).with_name("server.py")),
        "发布核心摘要不符",
    )
    server.require(
        set(release["toolHashes"]) == set(artifacts.TOOL_FILES),
        "发布辅助工具清单不完整",
    )
    for name, expected in release["toolHashes"].items():
        server.require(
            server.sha(ops / name) == expected, "发布辅助工具摘要不符：" + name
        )
    if not verify_package:
        return release, None
    package = ops / "release-code.tar.gz"
    if not package.exists():
        delta = ops / "code-delta.zip"
        expected = release["delta"]
        server.require(
            delta.stat().st_size == expected["bytes"] <= config["maxArchiveBytes"]
            and server.sha(delta) == expected["sha256"],
            "增量包身份不符",
        )
        artifacts.apply_delta(
            release["baseline"]["appRoot"], delta, package, config["maxExpandedBytes"]
        )
    expected = release["package"]
    server.require(
        not package.is_symlink()
        and package.stat().st_size == expected["bytes"] <= config["maxArchiveBytes"]
        and server.sha(package) == expected["sha256"],
        "服务器发布包 SHA-256 或大小不符",
    )
    server.require(
        server.archive_files(package, config["maxExpandedBytes"]) == release["files"],
        "服务器归档文件清单不符",
    )
    return release, package


def progress(ops, phase, **extra):
    server.write_json(
        ops / "progress.json",
        {"phase": phase, "at": datetime.now(timezone.utc).isoformat(), **extra},
    )


def status(ops):
    ops = Path(ops)
    for name in TERMINAL:
        path = ops / name
        if path.is_file():
            return {"receipt": name, **json.loads(path.read_text())}
    saved = (
        json.loads((ops / "progress.json").read_text())
        if (ops / "progress.json").exists()
        else {"phase": "等待启动"}
    )
    if (ops / "run.json").is_file():
        child = json.loads((ops / "run.json").read_text())
        try:
            running = server.process(child["pid"]) == child["identity"]
        except (OSError, ProcessLookupError):
            running = False
        if not running:
            return {
                "receipt": TERMINAL[2],
                "reasonType": "RunnerExitedWithoutReceipt",
                "retainDeployLock": True,
                "databaseRestored": False,
                **saved,
            }
    return {"pending": True, **saved}


def latest_status(config):
    latest = Path(config["opsParent"]) / "latest.json"
    if not latest.is_file():
        return {"noRelease": True}
    ops = operations_path(config, json.loads(latest.read_text())["operations"])
    return status(ops)


def launch(ops, fingerprint, action="publish"):
    config = server.load_config(ops / "remote-config.json")
    operations_path(config, ops)
    server.require(action in ("publish", "rollback"), "未知切换动作")
    verify_inputs(ops, fingerprint, config, verify_package=False)
    marker = ops / "launch.lock"
    with marker.open("x") as output:
        output.write(fingerprint)
    log = ops / "driver.private.log"
    command = [
        config["python"],
        str(ops / "protocol.py"),
        "run",
        "--ops",
        str(ops),
        "--manifest-sha",
        fingerprint,
        "--action",
        action,
        "--execute",
    ]
    with log.open("xb") as output:
        child = subprocess.Popen(
            command,
            cwd=ops,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=True,
        )
    try:
        identity = server.process(child.pid)
        server.write_json(ops / "run.json", {"pid": child.pid, "identity": identity})
    except (OSError, ProcessLookupError):
        server.require("receipt" in status(ops), "发布进程退出且缺少终态回执")
    return {"started": True, "pid": child.pid}


def rollback(config, release, ops, lock_state):
    server.require(
        not config.get("developmentMode", False),
        "开发模式只保留现用程序；请从 GitHub 指定提交生成恢复提交，经候选验收后重新发布，保留当前原始数据",
    )
    current_root = Path(server.launcher_root(config)).parent
    accepted = json.loads((current_root / "production-accepted.json").read_text())
    original = json.loads((current_root / "frozen-manifest.json").read_text())
    server.require(
        accepted["accepted"] is True and accepted["commit"] == original["commit"],
        "仅支持回退已接受的发布",
    )
    server.require(
        original["commit"] == release["baseline"]["commit"], "回退来源与观测身份不一致"
    )
    context = json.loads((current_root / "rollback-context.json").read_text())
    server.rollback_database_gate(config, original, context)
    previous = original["baseline"]["appRoot"]
    server.require(context["previousRoot"] == previous, "回退上下文与原基线不一致")
    server.verify_tree(previous, original["rollbackFiles"])
    server.verify_tree(original["appRoot"], original["files"])
    backup = Path(context["backup"])
    server.require(
        accepted["backup"] == str(backup), "回退备份不是已接受回执记录的备份"
    )
    server.require(
        backup.parent == current_root and not backup.is_symlink(),
        "回退备份目录身份错误",
    )
    hashes = json.loads((backup / "hashes.json").read_text())
    server.require(
        set(hashes) == {"app.toml", "launcher.sh", "meta.db"}, "回退备份摘要项不完整"
    )
    for name, expected in hashes.items():
        server.require(server.sha(backup / name) == expected, "回退备份摘要不符")
    server.require(
        server.sha(config["productionConfig"]) == hashes["app.toml"],
        "正式配置已变化，拒绝恢复旧启动器",
    )
    server.require(
        server.sha(backup / "launcher.sh") == context["previousLauncherSha256"],
        "回退启动器不是冻结的旧启动器",
    )
    baseline = server.baseline_gate(config, release)
    server.migration_gate(config, original, after=True)
    server.drain(config)
    server.baseline_gate(config, release)
    old = baseline["processes"]
    environments = {role: server.read_environment(item) for role, item in old.items()}
    server.disk_gate(
        config,
        ops,
        2 * server.database_bytes(config)
        + server.directory_bytes(Path(config["appData"]) / "static"),
    )
    server.backup(config, ops / "rollback-backup")
    static = Path(config["appData"]) / "static"
    previous_static = current_root / "static-previous-active"
    server.require(
        previous_static.is_dir()
        and previous_static.stat().st_dev == static.lstat().st_dev,
        "旧静态树缺失或不在同一文件系统",
    )
    identity = previous_static.lstat()
    expected_static = original["baseline"]["staticRoot"]
    server.require(
        identity.st_ino == expected_static["inode"]
        and identity.st_dev == expected_static["device"],
        "旧静态树身份已变化",
    )
    for name, expected in original["rollbackFiles"].items():
        if name.startswith("frontend/dist/") and name != "frontend/dist/index.html":
            path = previous_static / name.removeprefix("frontend/dist/")
            server.require(
                path.is_file() and server.sha(path) == expected["sha256"],
                "旧前端静态文件摘要已变化",
            )
    launched = {}
    try:
        server.stop(config, old["web"])
        server.drain(config)
        for role in server.ROLES[1:]:
            server.stop(config, old[role])
        server.require(
            not any(server.active_counts(config)[table] for table in server.ACTIVE),
            "回退最终排空出现新任务",
        )
        server.backup_database(config, ops / "rollback-backup/meta-quiesced.db")
        server.rollback_database_gate(config, original, context)
        server.operator_bootstrap(config, original, rollback=True)
        server.rollback_database_gate(config, original, context)
        os.replace(static, ops / "static-before-rollback")
        os.replace(previous_static, static)
        server.replace_launcher(config, (backup / "launcher.sh").read_bytes())
        restore_config = {
            **config,
            "expectedPreviousRoot": previous,
            "expectedRoleRoots": original.get("baselineRoleRoots", {}),
        }
        started = time.time()
        for role in (*server.ROLES[1:], "web"):
            server.start(
                restore_config,
                original["baseline"]["processes"],
                environments,
                previous,
                (role,),
                journal=launched,
            )
        server.wait_gate(restore_config, original, launched, started, old=True)
        server.rollback_database_gate(config, original, context)
        receipt = {
            "rolledBack": True,
            "commit": original["baseline"]["commit"],
            "previousRelease": original["commit"],
            **server.database_receipt(original, backup),
            "rollbackBackup": str(ops / "rollback-backup"),
            "at": datetime.now(timezone.utc).isoformat(),
        }
        server.write_json(ops / TERMINAL[1], receipt)
    except BaseException:
        lock_state["retainDeployLock"] = True
        raise


@contextmanager
def guarded_publication(config, fingerprint):
    with server.publication_locks(config, fingerprint) as state:
        try:
            yield state
        except server.ManualIntervention:
            state["retainDeployLock"] = True
            raise


def run_job(ops, fingerprint, action):
    config = server.load_config(ops / "remote-config.json")
    release = None
    try:
        progress(ops, "校验上传")
        release, package = verify_inputs(
            ops, fingerprint, config, verify_package=action != "rollback"
        )
        with guarded_publication(config, fingerprint) as lock_state:
            server.write_json(ops.parent / "latest.json", {"operations": str(ops)})
            if action == "rollback":
                progress(ops, "回退")
                rollback(config, release, ops, lock_state)
                return
            server.baseline_gate(config, release)
            if release["mode"] == "full":
                progress(ops, "候选验收")
                release["candidateAcceptance"] = candidate.run(
                    config,
                    release,
                    package,
                    ops,
                    json.loads((ops / "candidate-options.json").read_text()),
                )
                server.write_json(ops / "accepted-manifest.json", release)
                path = ops / "accepted-manifest.json"
            else:
                path = ops / "frozen-manifest.json"
            release, package = server.load_release(config, path, server.sha(path))
            progress(ops, "独立目录解包及迁移门禁")
            server.stage(config, release, package)
            server.write_json(
                Path(release["releaseDir"]) / "frozen-manifest.json", release
            )
            progress(ops, "排空、备份、切换及健康门禁")
            server.cutover(config, release, lock_state)
            if config.get("developmentMode", False):
                try:
                    development.prune_after_acceptance(config, release, ops)
                except Exception as cleanup_error:
                    server.write_json(
                        ops / "development-cleanup-pending.json",
                        {
                            "reason": str(cleanup_error),
                            "productionAccepted": True,
                            "at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
    except BaseException as error:
        if release is not None:
            for name in TERMINAL:
                path = Path(release["releaseDir"]) / name
                if path.is_file():
                    server.write_json(ops / name, json.loads(path.read_text()))
                    break
        if not any((ops / name).exists() for name in TERMINAL):
            server.write_json(
                ops / TERMINAL[2],
                {
                    "reasonType": type(error).__name__,
                    "retainDeployLock": Path(config["deployLock"]).exists(),
                    "databaseRestored": False,
                    "phase": status(ops).get("phase"),
                },
            )
        raise
    finally:
        if config.get("developmentMode", False):
            try:
                development.cleanup_candidate(config, ops)
            except Exception as cleanup_error:
                server.write_json(
                    ops / "candidate-cleanup-pending.json",
                    {
                        "reason": str(cleanup_error),
                        "at": datetime.now(timezone.utc).isoformat(),
                    },
                )
        if release is not None:
            for name in TERMINAL:
                path = Path(release["releaseDir"]) / name
                if path.is_file() and not (ops / name).exists():
                    server.write_json(ops / name, json.loads(path.read_text()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("launch", "run", "status"))
    parser.add_argument("--ops", type=Path, required=True)
    parser.add_argument("--manifest-sha")
    parser.add_argument("--action", choices=("publish", "rollback"), default="publish")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(status(args.ops), ensure_ascii=False))
        return
    server.require(args.execute, "服务器写入必须明确 --execute")
    os.umask(0o077)
    if args.command == "launch":
        print(json.dumps(launch(args.ops, args.manifest_sha, args.action)))
    else:

        def interrupted(signum, frame):
            raise server.ReleaseError("Release interrupted by signal")

        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        run_job(args.ops, args.manifest_sha, args.action)


if __name__ == "__main__":
    main()
