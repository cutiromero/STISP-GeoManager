"""建立独立候选数据副本，隔离历史后执行通用验收和可选钩子。"""

import json
from pathlib import Path
import shutil
import socket
import subprocess
import time

if __package__:
    from . import artifacts, compatibility, migrations, server
else:
    import artifacts
    import compatibility
    import migrations
    import server


def isolated_config(raw, root, port):
    original = raw["application"]["storage"]
    production = [
        Path(original[name]).resolve() for name in ("app_data", "research_data_root")
    ]
    for name, directory in (("app_data", "app"), ("research_data_root", "research")):
        target = root / directory
        server.require(
            target.resolve().is_relative_to(root.resolve()) and not target.is_symlink(),
            "候选数据目录越界",
        )
        for source in production:
            server.require(
                not target.resolve().is_relative_to(source)
                and not source.is_relative_to(target.resolve()),
                "候选数据与正式数据重叠",
            )
        original[name] = str(target)
    server.require(
        str(raw.get("compute", {}).get("mode", "docker")).strip().lower() == "native",
        "候选必须保留已核实的 native 运行策略",
    )
    runtime = raw["runtime"]
    runtime["allowed_hosts"] = ["127.0.0.1", "localhost", "testserver"]
    runtime["waitress_port"] = port
    runtime["disable_catalog_startup_scan"] = True
    runtime["disable_raster_startup_scan"] = True
    return raw


def run(config, release, package, operations, candidate_options):
    import tomlkit

    ops = Path(operations)
    root, code = ops / "candidate", ops / "candidate/code"
    server.require(ops.is_dir() and not ops.is_symlink(), "候选操作目录无效")
    server.require(
        not root.exists() and not root.is_symlink(), "候选目录已存在，不覆盖旧证据"
    )
    server.baseline_gate(config, release)
    port = candidate_options["port"]
    with socket.socket() as probe:
        server.require(probe.connect_ex(("127.0.0.1", port)) != 0, "候选端口已占用")
    server.require(
        server.archive_files(package, config["maxExpandedBytes"]) == release["files"],
        "候选包与冻结清单不一致",
    )
    server.disk_gate(
        config,
        ops,
        server.database_bytes(config)
        + sum(item["bytes"] for item in release["files"].values()),
    )
    raw = tomlkit.parse(Path(config["productionConfig"]).read_text())
    root.mkdir(mode=0o700)
    for directory in ("app", "research", "code"):
        (root / directory).mkdir(mode=0o700)
    raw = isolated_config(raw, root, port)
    config_path = root / "app.toml"
    with config_path.open("x") as output:
        output.write(tomlkit.dumps(raw))
    config_path.chmod(0o600)
    candidate_config = {
        **config,
        "appData": str(root / "app"),
        "researchData": str(root / "research"),
        "productionConfig": str(config_path),
        "baseUrl": f"http://127.0.0.1:{port}",
        "managementSeconds": candidate_options["commandSeconds"],
    }
    target_database = root / "app/database/meta.db"
    target_database.parent.mkdir(mode=0o700)
    server.backup_database(config, target_database)
    shutil.copy2(
        Path(config["appData"]) / "database/.secret_key",
        target_database.parent / ".secret_key",
    )
    (target_database.parent / ".secret_key").chmod(0o600)
    import tarfile

    with tarfile.open(package) as archive:
        archive.extractall(code, filter="data")
    server.verify_tree(code, release["files"])
    candidate_release = {**release, "appRoot": str(code)}
    server.migration_sources_gate(candidate_release)
    classification = release["migrationClassification"]
    server.require(classification["allowed"], migrations.rejection(classification))
    (code / ".runtime").mkdir(mode=0o700)
    (code / ".runtime/config-path").write_text(str(config_path))
    (code / ".runtime/config-path").chmod(0o600)
    baseline_applied = server.applied_migrations(candidate_config)
    baseline_plan = server.migration_plan(
        config, release["baseline"]["appRoot"], root / "baseline-migrations.private.log"
    )
    server.require(
        not baseline_plan["pending"] and baseline_plan["applied"] == baseline_applied,
        "候选副本的迁移记录与基线代码不一致",
    )
    server.manage(
        candidate_config, code, ["migrate", "--noinput"], root / "migrate.private.log"
    )
    migrated_state = server.database_state(candidate_config)
    server.require(
        migrated_state["appliedMigrations"]
        == sorted(baseline_applied + server.added_migration_ids(classification)),
        "候选迁移记录不符合新增集合",
    )
    legacy = compatibility.run(candidate_config, release, root)
    server.verify_database_state(candidate_config, migrated_state)
    isolation_script = (
        "import sys;sys.path.insert(0," + repr(str(ops)) + ");"
        "import candidate_support as support;support.configure(" + repr(str(ops)) + ");"
        "support.bootstrap();support.isolate();support.require_isolated()"
    )
    with (root / "isolate.private.log").open("xb") as output:
        subprocess.run(
            [config["python"], "-c", isolation_script],
            cwd=code,
            env=server.environment(candidate_config, code),
            stdout=output,
            stderr=subprocess.STDOUT,
            timeout=candidate_options["commandSeconds"],
            check=True,
        )
    isolation = json.loads((ops / "candidate-isolation.json").read_text())
    server.require(
        isolation["isolated"] is True
        and Path(isolation["database"]["path"]) == target_database.resolve(),
        "候选数据库未完成历史隔离",
    )
    for label, args in (
        ("check", ["check"]),
        ("schema", ["makemigrations", "--check", "--dry-run"]),
        ("collectstatic", ["collectstatic", "--noinput", "--verbosity", "0"]),
        (
            "archive-previous",
            [
                "archive_frontend_assets",
                "--source",
                str(Path(release["baseline"]["appRoot"]) / "frontend/dist"),
            ],
        ),
        (
            "archive-candidate",
            ["archive_frontend_assets", "--source", str(code / "frontend/dist")],
        ),
    ):
        server.manage(candidate_config, code, args, root / (label + ".private.log"))
    checks = {
        "databaseCopiedAndChecked": True,
        "historyQuarantined": True,
        "isolatedRoots": True,
        "djangoCheck": True,
        "modelSchemaCheck": True,
        "staticArchived": True,
    }
    started = {}
    try:
        for role in (*server.ROLES[1:], "web"):
            if role == "web":
                command = [
                    config["python"],
                    config["waitress"],
                    "--host=127.0.0.1",
                    f"--port={port}",
                    "--threads=8",
                    "--connection-limit=100",
                    "--channel-timeout=720",
                    "geomanager.wsgi:application",
                ]
            else:
                command = [
                    config["python"],
                    str(code / "backend/manage.py"),
                    role,
                    "--config",
                    str(config_path),
                ]
            log = root / (role + ".private.log")
            with log.open("xb") as output:
                child = subprocess.Popen(
                    command,
                    cwd=code / "backend",
                    env=server.environment(candidate_config, code),
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            time.sleep(config["startVerificationSeconds"])
            try:
                identity = server.process(child.pid)
            except BaseException:
                if child.poll() is None:
                    raise server.UnknownStartedProcess(child.pid) from None
                raise server.ReleaseError("候选进程启动后立即退出") from None
            started[role] = identity
            server.require(
                identity["argv"] == command
                and identity["cwd"] == str(code / "backend"),
                "候选进程身份不符",
            )
        server.wait_gate(candidate_config, release, started, time.time())
        checks["httpProcessHeartbeatAndStatic"] = True
        hook = release.get("candidateHook")
        if hook:
            path = ops / "candidate-check.py"
            server.require(server.sha(path) == hook["sha256"], "候选钩子摘要不符")
            context = ops / "candidate-context.json"
            server.write_json(
                context,
                {
                    "commit": release["commit"],
                    "version": release["version"],
                    "root": str(root),
                    "code": str(code),
                    "config": str(config_path),
                    "baseUrl": candidate_config["baseUrl"],
                },
            )
            with (root / "hook.private.log").open("xb") as output:
                subprocess.run(
                    [config["python"], str(path), "--context", str(context)],
                    cwd=code,
                    env=server.environment(candidate_config, code),
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    timeout=candidate_options["hookSeconds"],
                    check=True,
                )
            hook_receipt = json.loads(
                (root / "hook.private.log").read_text().splitlines()[-1]
            )
            server.require(
                hook_receipt.get("accepted") is True
                and hook_receipt.get("checks")
                and all(value is True for value in hook_receipt["checks"].values()),
                "候选钩子未明确接受所有检查",
            )
            checks["customHook"] = True
    finally:
        cleanup_errors = []
        for role in ("web", *server.ROLES[1:]):
            if role in started:
                try:
                    server.stop(candidate_config, started[role])
                except BaseException as error:
                    cleanup_errors.append(type(error).__name__)
        if cleanup_errors:
            raise server.ManualIntervention("候选进程未能全部按身份正常停止")
    server.baseline_gate(config, release)
    server.verify_database_state(candidate_config, migrated_state)
    receipt = artifacts.acceptance(release, checks)
    receipt["migrationEvidence"] = {
        "archiveSha256": release["package"]["sha256"],
        "classificationDigest": server.digest(classification),
        "databaseState": migrated_state,
        "baselineAppliedMigrations": baseline_applied,
        "compatibility": legacy,
    }
    server.migration_evidence_gate({**release, "candidateAcceptance": receipt})
    server.write_json(ops / "candidate-accepted.json", receipt)
    return receipt
