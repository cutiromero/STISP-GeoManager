"""独立临时目录夹具，不启动真实进程、不访问网络。"""

import json
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace

import pytest

from tools.release import artifacts, config as configuration, server

ROOT = Path(__file__).resolve().parents[3]
TEST_BUILD_RESOURCES = [
    "frontend/src/assets/team/han-yang.jpeg",
    "frontend/src/assets/team/sun-shuhui.jpeg",
    "frontend/src/assets/team/gao-danning.jpeg",
    "frontend/src/assets/portal/results-showcase-20260924.png",
]


@pytest.fixture
def config():
    value = configuration.load(ROOT / "tools/release/config.example.toml")
    value["local"]["buildResources"] = list(TEST_BUILD_RESOURCES)
    return value


@pytest.fixture
def layout(tmp_path, monkeypatch, config):
    previous = tmp_path / "geomanager-release-0.3.0-aaaaaaa-old/code"
    previous.mkdir(parents=True)
    for name, content in {
        "backend/manage.py": "print('管理入口')\n",
        "backend/pyproject.toml": '[project]\nversion="0.3.0"\n',
        "frontend/package.json": '{"version":"0.3.0"}',
        "frontend/dist/index.html": '<script src="/static/assets/old.js"></script>',
        "frontend/dist/assets/old.js": "console.log('old')",
    }.items():
        path = previous / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (previous.parent / "staged.json").write_text(json.dumps({"commit": "a" * 40}))
    old_files = artifacts.tree_files(previous)
    launcher = tmp_path / "start.sh"
    launcher.write_text(f"#!/bin/sh\nAPP_ROOT={previous}\nWORKER_APP_ROOT={previous}\n")
    launcher.chmod(0o700)
    app = tmp_path / "app"
    (app / "database").mkdir(parents=True)
    database = app / "database/meta.db"
    with sqlite3.connect(database) as connection:
        for table in server.ACTIVE:
            connection.execute(f'CREATE TABLE "{table}" (status TEXT)')
        connection.execute("CREATE TABLE marker (value TEXT)")
        connection.execute("CREATE TABLE django_migrations (app TEXT, name TEXT)")
        connection.execute(
            "INSERT INTO django_migrations VALUES ('app', '0001_initial')"
        )
        connection.execute("INSERT INTO marker VALUES ('不可恢复覆盖')")
    (app / "static/assets").mkdir(parents=True)
    (app / "static/assets/old.js").write_text("console.log('old')")
    (app / "database/.secret_key").write_text("仅为临时隔离测试的非真实值")
    production = tmp_path / "app.toml"
    production.write_text(
        f'[application.storage]\napp_data="{app}"\nresearch_data_root="{tmp_path / "research"}"\n'
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    runtime = {
        **config["server"],
        "launcher": str(launcher),
        "productionConfig": str(production),
        "appData": str(app),
        "researchData": str(tmp_path / "research"),
        "logDir": str(logs),
        "releaseParent": str(tmp_path),
        "opsParent": str(tmp_path / "operations"),
        "publishLock": str(tmp_path / "publish.lock"),
        "deployLock": str(tmp_path / "DEPLOY.lock"),
        "expectedPreviousRoot": str(previous),
        "expectedLauncherSha256": server.sha(launcher),
    }
    processes = {}
    states = {"pids": {}, "counter": 10000, "events": []}
    for offset, role in enumerate(server.ROLES, 1000):
        argv = [runtime["python"], str(previous / "backend/manage.py"), role]
        if role == "web":
            argv = [
                runtime["python"],
                runtime["waitress"],
                "--host=0.0.0.0",
                "--port=6007",
                "--threads=8",
                "--connection-limit=100",
                "--channel-timeout=720",
                "geomanager.wsgi:application",
            ]
        processes[role] = {
            "pid": offset,
            "startTicks": offset,
            "cwd": str(previous / "backend"),
            "argv": argv,
        }
        states["pids"][offset] = processes[role]
    states["active"] = dict(processes)

    def discover(current, root):
        assert all(
            server.role_of(item, current, root) == role
            for role, item in states["active"].items()
        )
        return dict(states["active"])

    def process(pid):
        if int(pid) not in states["pids"]:
            raise FileNotFoundError(pid)
        return states["pids"][int(pid)]

    def stop(current, item):
        server.ensure_identity(item)
        states["events"].append(("stop", item["pid"]))
        states["pids"].pop(item["pid"])
        for role, active in list(states["active"].items()):
            if active == item:
                states["active"].pop(role)

    def start(current, templates, environments, root, roles=server.ROLES, journal=None):
        result = {} if journal is None else journal
        for role in roles:
            states["counter"] += 1
            source_root = server.previous_role_root(current, role)
            destination = (
                source_root if root == current["expectedPreviousRoot"] else root
            )
            item = {
                "pid": states["counter"],
                "startTicks": states["counter"],
                "cwd": templates[role]["cwd"].replace(source_root, destination),
                "argv": [
                    part.replace(source_root, destination)
                    for part in templates[role]["argv"]
                ],
            }
            assert server.role_of(item, current, root) == role
            result[role] = item
            states["pids"][item["pid"]] = item
            states["active"][role] = item
            states["events"].append(("start", role, root))
        return result

    def manage(current, root, args, log):
        states["events"].append(("manage", tuple(args)))
        text = "[X] app.0001_initial\n" if args[0] == "showmigrations" else "通过\n"
        Path(log).write_text(text)
        return text

    monkeypatch.setattr(server, "discover", discover)
    monkeypatch.setattr(server, "process", process)
    monkeypatch.setattr(server, "stop", stop)
    monkeypatch.setattr(server, "start", start)
    monkeypatch.setattr(server, "read_environment", lambda item: {"TEST_ONLY": "yes"})
    monkeypatch.setattr(server, "manage", manage)
    monkeypatch.setattr(
        server,
        "worker_locks",
        lambda current, items: {
            role: [items[role]["pid"]] for role in server.ROLES[1:]
        },
    )
    monkeypatch.setattr(
        server,
        "protected_listeners",
        lambda: {"19000": [{"pid": 88, "startTicks": 89}]},
    )
    monkeypatch.setattr(
        server,
        "wait_gate",
        lambda *args, **kwargs: states["events"].append(
            ("health", kwargs.get("old", False))
        ),
    )

    target = tmp_path / "geomanager-release-0.3.0-bbbbbbb-new"

    def run(command, **kwargs):
        assert command[:2] == [runtime["python"], "-c"]
        prepared = target / "static-next"
        shutil.copytree(target / "code/frontend/dist", prepared)
        states["events"].append(("collectstatic",))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(server.subprocess, "run", run)
    baseline = {**server.inspect(runtime), "commit": "a" * 40, "version": "0.3.0"}
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    source = tmp_path / "source"
    shutil.copytree(previous, source)
    (source / "frontend/dist/index.html").write_text(
        '<script src="/static/assets/new.js"></script>'
    )
    (source / "frontend/dist/assets/old.js").unlink()
    (source / "frontend/dist/assets/new.js").write_text("console.log('new')")
    files = artifacts.tree_files(source)
    package = artifacts.write_package(
        files,
        lambda name: (source / name).read_bytes(),
        incoming / "release-code.tar.gz",
    )
    release = {
        "schema": 1,
        "commit": "b" * 40,
        "version": "0.3.0",
        "mode": "fast",
        "noSchemaChanges": True,
        "scientificOperatorsUnchanged": True,
        "ancestorVerified": True,
        "releaseDir": str(target),
        "appRoot": str(target / "code"),
        "files": files,
        "baseline": baseline,
        "rollbackFiles": old_files,
        "releaseToolSha256": server.sha(server.__file__),
        "package": package,
        "entryJavascript": ["/static/assets/new.js"],
    }
    release["preflightAcceptance"] = artifacts.acceptance(release, {"test": True})
    manifest = incoming / "frozen-manifest.json"
    server.write_json(manifest, release)
    return SimpleNamespace(
        config=runtime,
        release=release,
        package=incoming / "release-code.tar.gz",
        manifest=manifest,
        previous=previous,
        target=target,
        source=source,
        state=states,
    )
