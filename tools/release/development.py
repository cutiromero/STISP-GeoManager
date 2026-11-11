"""开发模式验收后只留当前应用；历史代码从 Git 重建。"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil

if __package__:
    from . import server
else:
    import server

# 配置：保留轻量追溯信息；禁止删除运行中目录和数据根目录。
KEEP_OPERATION_RECORDS = 10
TERMINAL = ("production-accepted.json", "production-rolled-back.json")
PROC_ROOT = Path("/proc")


def require_inactive(path):
    for process in PROC_ROOT.iterdir():
        if not process.name.isdigit():
            continue
        links = [process / "cwd", process / "exe"]
        try:
            links.extend((process / "fd").iterdir())
        except OSError:
            pass
        for link in links:
            try:
                value = Path(os.readlink(link))
            except OSError:
                continue
            server.require(
                not value.is_relative_to(path),
                "目录仍被运行进程使用，保留：" + str(path),
            )


def remove_owned(path, boundary, removed):
    path, boundary = Path(path), Path(boundary).resolve()
    if not path.exists() and not path.is_symlink():
        return
    server.require(not path.is_symlink(), "清理目录不能为符号链接：" + str(path))
    resolved = path.resolve()
    server.require(
        resolved != boundary and resolved.is_relative_to(boundary), "清理范围越界"
    )
    require_inactive(resolved)
    if resolved.is_dir():
        shutil.rmtree(resolved)
    else:
        resolved.unlink()
    removed.append(str(path))


def cleanup_candidate(config, operations):
    if not config.get("developmentMode", False):
        return []
    root = Path(operations) / "candidate"
    if not root.exists():
        return []
    server.require(
        root.resolve().is_relative_to(Path(config["opsParent"]).resolve()),
        "候选目录越界",
    )
    require_inactive(root.resolve())
    removed = []
    for name in ("app", "research", "code", "compatibility-code", "baseline-code"):
        remove_owned(root / name, root, removed)
    server.write_json(
        Path(operations) / "candidate-storage-cleanup.json", {"removed": removed}
    )
    return removed


def remove_packages(operations, removed):
    for path in Path(operations).iterdir():
        if path.is_file() and path.name.endswith((".tar.gz", ".tgz", ".zip")):
            remove_owned(path, operations, removed)


def prune_after_acceptance(config, release, operations):
    if not config.get("developmentMode", False):
        return {"enabled": False}
    root = Path(release["releaseDir"]).resolve()
    parent = Path(config["releaseParent"]).resolve()
    server.require(root.parent == parent, "正式发布目录不在已核实根目录")
    server.require(
        Path(server.launcher_root(config)).resolve()
        == Path(release["appRoot"]).resolve(),
        "启动器尚未指向本次验收版本",
    )
    accepted = json.loads((root / "production-accepted.json").read_text())
    server.require(
        accepted.get("accepted") is True
        and accepted.get("commit") == release["commit"],
        "仅对已验收版本执行开发清理",
    )
    before = shutil.disk_usage(parent).free
    removed = cleanup_candidate(config, operations)
    old = Path(release["baseline"]["appRoot"]).resolve().parent
    if old != root:
        server.require(
            old.parent == parent and old.name.startswith("geomanager-release-"),
            "上一程序目录身份异常，保留",
        )
        remove_owned(old, parent, removed)
    for name in ("static-previous-active", "static-next", "static-failed-new"):
        remove_owned(root / name, root, removed)
    remove_packages(operations, removed)
    completed = []
    for path in Path(config["opsParent"]).iterdir():
        if path.is_dir() and not path.is_symlink() and path != Path(operations):
            receipt = next(
                (path / name for name in TERMINAL if (path / name).is_file()), None
            )
            if receipt:
                completed.append((path, receipt))
    completed.sort(key=lambda item: item[0].name, reverse=True)
    for index, (path, receipt) in enumerate(completed):
        if index < KEEP_OPERATION_RECORDS - 1:
            removed += cleanup_candidate(config, path)
            remove_packages(path, removed)
            continue
        summary = json.loads(receipt.read_text())
        history = Path(config["opsParent"]) / "history"
        server.write_json(
            history / (path.name + ".json"),
            {
                key: summary[key]
                for key in (
                    "commit",
                    "version",
                    "accepted",
                    "rolledBack",
                    "at",
                    "databaseRestored",
                )
                if key in summary
            },
        )
        remove_owned(path, Path(config["opsParent"]), removed)
    report = {
        "enabled": True,
        "at": datetime.now(timezone.utc).isoformat(),
        "removed": removed,
        "freedBytes": shutil.disk_usage(parent).free - before,
        "codeHistory": "GitHub commit",
        "databaseRestored": False,
        "permanentDatabaseSnapshots": False,
        "retainedCompiledVersions": 1,
    }
    server.write_json(root / "development-retention.json", report)
    server.write_json(Path(operations) / "development-retention.json", report)
    return report
