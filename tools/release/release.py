"""STISP 标准发布入口；默认完整离线计划，--execute 才允许连接服务器。"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

if __package__:
    from . import artifacts, config as configuration, server
    from .executor import Executor
else:
    import artifacts
    import config as configuration
    import server
    from executor import Executor

REPO = Path(__file__).resolve().parents[2]
RECEIPTS = REPO / ".runtime/releases"
PUBLISH_STEPS = (
    "读取正式启动器、提交、四类进程、任务队列、磁盘和双锁；冻结身份快照",
    "已跟踪文件干净、列出未跟踪文件、当前固定个人分支、HEAD 与 origin 个人分支精确一致；验证正式提交祖先关系",
    "比较迁移、科学算子、前端输入；fast 遇到任何迁移拒绝；full 用 AST 逐操作分类，拒绝项须人工制定方案",
    "在系统临时目录的英文路径 git archive 精确提交，排除已知开发说明链接",
    "前端有变化：复制并摘要本机资源、用配置的 pnpm 前缀 run build:verify（/static/）、移除构建输入资源；无变化：核对正式前端逐文件 SHA-256 后复用",
    "生成可复现完整包、增量包、文件清单；冻结启动器、工具、包和清单摘要",
    "创建独立远端操作目录；SCP 上传较小的包和固定工具；服务器校验并按需重建完整包",
    "独立会话启动，持有双发布锁；重新核对完整基线、解包到全新发布目录",
    "迁移源码和已应用状态门禁；排空任务；备份数据库、配置、静态文件和启动器",
    "归档旧/新完整前端公共依赖，独立 collectstatic；停 web、二次排空、停三个 worker、静止备份",
    "静止备份后 migrate；无迁移须 schema 不变，有新增须正式结构指纹及迁移记录等于候选；再切静态树和两个 APP_ROOT、启动 worker 后启动 web",
    "进程身份、worker 锁/心跳、依赖服务、健康接口、首页 JS 摘要与 Content-Type 硬检查",
    "轮询直至已接受/已回滚/需人工处理；取回清单和回执；删除临时源码与发布包",
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("inspect", "fast", "full", "status", "rollback")
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="允许实际连接和执行；inspect/status 也需明确指定",
    )
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument(
        "--candidate-check", type=Path, help="在候选服务器运行的 Python 验收脚本"
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="仅验证导出/前端/打包，不连接、不执行发布前置检查、不生成接受回执",
    )
    parser.add_argument("--base-commit", help="离线演练的精确基线 Git revision")
    parser.add_argument(
        "--baseline-package", type=Path, help="只读的本机上一发布包，仅用于离线演练"
    )
    args = parser.parse_args(argv)
    if args.local_only and (
        args.execute
        or args.command not in ("fast", "full")
        or not args.base_commit
        or not args.baseline_package
    ):
        parser.error(
            "--local-only 只用于 fast/full，须提供 --base-commit 和 --baseline-package，不能同时 --execute"
        )
    if args.candidate_check and args.command != "full":
        parser.error("--candidate-check 只能用于 full")
    return args


def remote(executor, config, expression, *, binary=False):
    tools = Path(__file__).parent
    sources = {name[:-3]: (tools / name).read_text() for name in artifacts.TOOL_FILES}
    payload = (
        "import sys,types,json,os\n"
        "sources=" + repr(sources) + "\n"
        "for name,source in sources.items():\n"
        " module=types.ModuleType(name);module.__file__='<read-only-'+name+'>';sys.modules[name]=module;exec(compile(source,module.__file__,'exec'),module.__dict__)\n"
        "config=" + repr(config["server"]) + "\n"
        "import protocol\n"
        + (
            expression
            if binary
            else "print(json.dumps(" + expression + ",ensure_ascii=False))"
        )
    ).encode()
    result = executor.ssh(
        [config["server"]["python"], "-c", "import sys;exec(sys.stdin.read())"],
        payload=payload,
    )
    return result if binary else json.loads(result)


def plan(args, config, repo, emit=print):
    commit = artifacts.commit_id(repo, args.commit)
    ssh = config["ssh"]
    emit(
        f"{args.command} 离线计划；不会连接 {ssh['user']}@{ssh['host']}:{ssh['port']}，不会写服务器。"
    )
    emit(
        f"本机待发布提交：{commit}；分支：{artifacts.git(repo, 'branch', '--show-current')}"
    )
    emit(
        f"正式入口：{config['server']['baseUrl']}；启动器：{config['server']['launcher']}"
    )
    emit(
        f"解释器：{config['server']['python']}；Waitress：{config['server']['waitress']}"
    )
    emit(f"正式配置：{config['server']['productionConfig']}")
    emit(
        f"业务根：{config['server']['appData']}；科研根：{config['server']['researchData']}"
    )
    emit(
        f"日志：{config['server']['logDir']}；操作证据根：{config['server']['opsParent']}"
    )
    emit(f"双锁：{config['server']['deployLock']}；{config['server']['publishLock']}")
    emit(
        f"本机构建：{shlex.join([*config['local']['pnpm'], 'run', 'build:verify'])}；候选选项：{config['candidate']}"
    )
    emit("本机构建资源：" + "、".join(config["local"]["buildResources"]))
    emit("未跟踪文件（不阻断，不作为源码入包）：")
    for name in artifacts.untracked_files(repo):
        emit("  " + name)
    emit(
        f"新发布目录：{config['server']['releaseParent']}/geomanager-release-<版本>-{commit[:7]}-<自动时间标识>/code"
    )
    emit("正式提交、上一根目录、角色根、启动器摘要与清单摘要均运行时读取，离线不猜测。")
    if args.command in ("fast", "full"):
        for number, step in enumerate(PUBLISH_STEPS, 1):
            emit(f"{number}. {step}")
            if args.command == "full" and number == 7:
                emit(
                    "7a. 独立候选：备份正式元数据库、复制 secret key（不输出）、重定向 app/research，保留 native 策略并禁启动扫描。"
                )
                emit(
                    "7b. 候选迁移、记录结构指纹及迁移记录；基线 manage.py check、只读及回滚事务 INSERT 兼容检查；保留历史隔离、新代码 check/静态归档、四角色健康门禁与可选钩子。"
                )
        if args.command == "full":
            emit(
                "迁移规则：仅新表、可空或带 db_default 的新增列、新表索引/约束及可证明只写同迁移新表的数据操作；拒绝删改重命名、已有表唯一约束与无法判断的操作。分类、候选指纹、旧代码兼容证据必须绑定同一包摘要。"
            )
        emit(
            "失败：切换后健康失败仅回滚代码/启动器/静态树；数据库结构保持前进，回执记录旧代码兼容证据和静止备份位置。结构指纹/迁移记录或进程身份不明保留 DEPLOY.lock，转人工，永不恢复数据库。"
        )
    elif args.command == "inspect":
        emit(
            "只读：经 SSH 内存执行固定观测代码，不上传脚本；输出正式根、提交、版本、四类进程、分状态队列、余量与锁。"
        )
        emit("以本机 Git 比较正式提交和目标提交，输出顶层目录、迁移、算子和前端变化。")
    elif args.command == "status":
        emit(
            "读取本机最近回执；--execute 时只读查询远端最近进度/终态，不启动或恢复任何进程。"
        )
        if RECEIPTS.exists():
            latest = sorted(RECEIPTS.iterdir())[-1:]
            if latest:
                emit(f"最近本机记录：{latest[0]}")
    else:
        emit(
            "读取当前已接受清单与 rollback-context；验证旧代码、旧启动器、备份、当前配置、schema 和双锁。"
        )
        emit(
            "结构比旧代码新时，先核对同包分类、候选指纹、旧代码兼容证据及迁移记录，全部匹配才允许回退；永不执行逆迁移或恢复数据库。"
        )
        emit(
            "独立会话：排空、备份当前状态、停 web/worker、保存静止数据库、恢复上一个静态树和启动器、原身份启动旧代码并过健康门禁。"
        )
        emit("不还原数据库；失败保留锁并给需人工处理回执，不盲目重试。")
    emit(
        f"超时/阈值：{json.dumps({name: value for name, value in config['server'].items() if isinstance(value, (int, float, list))}, ensure_ascii=False)}"
    )
    emit(
        "执行须明确 --execute；仅离线构建使用 --local-only --base-commit <SHA> --baseline-package <归档>。"
    )


def record_id(commit):
    return (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + commit[:7]
        + "-"
        + uuid.uuid4().hex[:6]
    )


def save_local_logs(work, output):
    for name in ("build.log", "timings.json", "build-resources.json"):
        if (work / name).is_file():
            shutil.copy2(work / name, output / name)


def local_stages(args, config, repo):
    commit = artifacts.commit_id(repo, args.commit)
    base = artifacts.commit_id(repo, args.base_commit)
    summary = artifacts.diff_summary(repo, base, commit)
    identifier = record_id(commit)
    output = RECEIPTS / identifier
    output.mkdir(mode=0o700, parents=True)
    print(f"本机记录：{output}", flush=True)
    print(
        "仅本机演练：不核实 origin、不忽略真实发布的脏工作区门禁，也不生成正式接受回执。"
    )
    files = server.archive_files(
        args.baseline_package, config["server"]["maxExpandedBytes"]
    )
    expected = {
        name: value
        for name, value in files.items()
        if name.startswith("frontend/dist/")
    }
    baseline_sources = artifacts.git_files(repo, base)
    server.require(
        all(files.get(name) == value for name, value in baseline_sources.items()),
        "离线基线包源码与所选基线提交不一致",
    )
    with tempfile.TemporaryDirectory(
        prefix="stisp-release-",
        dir="/private/tmp" if Path("/private/tmp").exists() else None,
    ) as directory:
        work = Path(directory)
        try:
            artifact = artifacts.package_source(
                repo,
                commit,
                base,
                work,
                config,
                summary,
                baseline_package=args.baseline_package,
                baseline_frontend=expected,
                baseline_files={**baseline_sources, **expected},
            )
            manifest = {
                **artifact,
                "localOnly": True,
                "deployable": False,
                "diff": summary,
                "untrackedFiles": artifacts.untracked_files(repo),
            }
            server.write_json(output / "manifest.json", manifest)
            server.write_json(
                output / "receipt.json",
                {
                    "localOnly": True,
                    "deployable": False,
                    "commit": commit,
                    "untrackedFiles": manifest["untrackedFiles"],
                    "buildResources": artifact["buildResources"],
                    "timings": artifact["timings"],
                },
            )
            print(
                json.dumps(
                    {
                        "localOnly": True,
                        "record": str(output),
                        "timings": artifact["timings"],
                        "package": artifact["package"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        finally:
            save_local_logs(work, output)


def upload_job(
    executor, config, work, manifest, identifier, *, action="publish", hook=None
):
    operations = str(Path(config["server"]["opsParent"]) / identifier)
    runtime = {
        **config["server"],
        "expectedPreviousRoot": manifest["baseline"]["appRoot"],
        "expectedLauncherSha256": manifest["baseline"]["launcherSha256"],
        "expectedRoleRoots": manifest["baseline"].get("roleRoots", {}),
    }
    if manifest["baseline"]["staticRoot"]["isLink"]:
        runtime["expectedStaticLinkTarget"] = manifest["baseline"]["staticRoot"][
            "target"
        ]
    server.write_json(work / "remote-config.json", runtime)
    server.write_json(work / "candidate-options.json", config["candidate"])
    server.write_json(work / "frozen-manifest.json", manifest)
    remote(
        executor, config, "protocol.create_operations(config," + repr(operations) + ")"
    )
    for name in artifacts.TOOL_FILES:
        executor.upload(Path(__file__).with_name(name), operations + "/" + name)
    for name in (
        "remote-config.json",
        "candidate-options.json",
        "frozen-manifest.json",
    ):
        executor.upload(work / name, operations + "/" + name)
    if hook:
        executor.upload(hook, operations + "/candidate-check.py")
    if action != "rollback":
        name = (
            "code-delta.zip"
            if manifest["delta"]["bytes"] < manifest["package"]["bytes"]
            else "release-code.tar.gz"
        )
        executor.upload(work / name, operations + "/" + name)
    fingerprint = server.sha(work / "frozen-manifest.json")
    return operations, fingerprint


def wait_job(executor, config, operations, fingerprint, output, *, action="publish"):
    scope = server.digest([config["ssh"], config["server"]["opsParent"]])
    server.write_json(
        output / "request.json",
        {
            "operations": operations,
            "manifestSha256": fingerprint,
            "action": action,
            "scope": scope,
        },
    )
    try:
        executor.ssh(
            [
                config["server"]["python"],
                operations + "/protocol.py",
                "launch",
                "--ops",
                operations,
                "--manifest-sha",
                fingerprint,
                "--action",
                action,
                "--execute",
            ]
        )
    except subprocess.CalledProcessError as error:
        if error.returncode != 255:
            raise
        print("启动 SSH 连接中断：不重发切换指令，继续只读轮询。", flush=True)
    except subprocess.TimeoutExpired:
        print(
            "启动连接中断：不重发切换指令，继续只读轮询；可另开终端使用 status --execute。",
            flush=True,
        )
    while True:
        try:
            result = remote(
                executor, config, "protocol.status(" + repr(operations) + ")"
            )
        except subprocess.CalledProcessError as error:
            if error.returncode != 255:
                raise
            print("状态 SSH 连接中断，等待重连。", flush=True)
            time.sleep(config["local"]["statusPollSeconds"])
            continue
        except subprocess.TimeoutExpired:
            print("状态连接中断，等待重连；不会停止服务器独立会话。", flush=True)
            time.sleep(config["local"]["statusPollSeconds"])
            continue
        with (output / "progress.log").open("a") as stream:
            stream.write(json.dumps(result, ensure_ascii=False) + "\n")
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if "receipt" in result:
            server.write_json(output / "receipt.json", result)
            return result
        time.sleep(config["local"]["statusPollSeconds"])


def publish(args, config, repo, executor):
    commit = artifacts.commit_id(repo, args.commit)
    untracked = artifacts.preflight(repo, commit, config["local"]["branch"])
    server.require(
        executor.origin_head(repo, config["local"]["branch"]) == commit,
        "origin 个人分支尚未包含精确 HEAD，拒绝发布",
    )
    baseline = remote(executor, config, "protocol.describe(config)")
    previous_files = artifacts.verified_baseline_files(repo, baseline)
    server.require(
        not baseline["locks"]["deployExists"]
        and not baseline["locks"]["publishOwners"],
        "正式发布锁已存在或被持有，先人工核查",
    )
    summary = artifacts.diff_summary(repo, baseline["commit"], commit)
    if args.command == "fast":
        server.require(
            not artifacts.fast_reasons(summary),
            "；".join(artifacts.fast_reasons(summary)),
        )
    identifier = record_id(commit)
    output = RECEIPTS / identifier
    output.mkdir(mode=0o700, parents=True)
    print(f"本机记录：{output}", flush=True)
    with tempfile.TemporaryDirectory(
        prefix="stisp-release-",
        dir="/private/tmp" if Path("/private/tmp").exists() else None,
    ) as directory:
        work = Path(directory)
        try:
            baseline_package = None
            if not summary["frontendChanged"]:
                baseline_package = work / "previous-frontend.tar.gz"
                baseline_package.write_bytes(
                    remote(
                        executor,
                        config,
                        "protocol.stream_frontend(config," + repr(baseline) + ")",
                        binary=True,
                    )
                )
            artifact = artifacts.package_source(
                repo,
                commit,
                baseline["commit"],
                work,
                config,
                summary,
                baseline_package=baseline_package,
                baseline_frontend=baseline["frontendFiles"],
                baseline_files=previous_files,
            )
            manifest = artifacts.freeze(
                artifact, baseline, summary, config, args.command, identifier
            )
            manifest["untrackedFiles"] = untracked
            manifest["rollbackFiles"] = previous_files
            manifest["baselineRoleRoots"] = baseline["roleRoots"]
            classification = artifacts.classify_migrations(
                manifest, previous_files, work / "source"
            )
            server.write_json(output / "migration-classification.json", classification)
            server.require(
                classification["allowed"],
                artifacts.migrations.rejection(classification),
            )
            if args.candidate_check:
                server.require(args.candidate_check.is_file(), "候选钩子脚本不存在")
                manifest["candidateHook"] = {"sha256": server.sha(args.candidate_check)}
            server.write_json(output / "manifest.json", manifest)
            operations, fingerprint = upload_job(
                executor, config, work, manifest, identifier, hook=args.candidate_check
            )
            result = wait_job(executor, config, operations, fingerprint, output)
            result["untrackedFiles"] = untracked
            result["buildResources"] = artifact["buildResources"]
            server.write_json(output / "receipt.json", result)
            if result.get("accepted") is True:
                server.require(
                    result.get("commit") == commit
                    and result.get("version") == manifest["version"],
                    "正式接受回执与本机冻结提交/版本不一致",
                )
            if args.command == "full":
                evidence = remote(
                    executor,
                    config,
                    "json.loads((protocol.Path("
                    + repr(operations)
                    + ")/'accepted-manifest.json').read_text()) if (protocol.Path("
                    + repr(operations)
                    + ")/'accepted-manifest.json').exists() else None",
                )
                if evidence:
                    server.require(
                        all(
                            evidence.get(name) == manifest[name]
                            for name in (
                                "commit",
                                "version",
                                "package",
                                "files",
                                "baseline",
                                "releaseToolSha256",
                            )
                        ),
                        "最终候选清单与本机冻结内容不一致",
                    )
                    server.write_json(output / "manifest.json", evidence)
            server.require(
                result.get("accepted") is True,
                "发布未被接受，请查看本机回执；不要自动重试或移除发布锁",
            )
        finally:
            save_local_logs(work, output)


def explicit_rollback(args, config, executor):
    baseline = remote(executor, config, "protocol.describe(config)")
    server.require(
        baseline["rollbackAvailable"], "当前正式目录没有标准工具记录的可验证回退上下文"
    )
    identifier = record_id(baseline["commit"])
    output = RECEIPTS / identifier
    output.mkdir(mode=0o700, parents=True)
    with tempfile.TemporaryDirectory(prefix="stisp-release-") as directory:
        work = Path(directory)
        manifest = {
            "commit": baseline["commit"],
            "baseline": baseline,
            "releaseDir": str(Path(config["server"]["opsParent"]) / identifier),
            "releaseToolSha256": server.sha(Path(__file__).with_name("server.py")),
            "toolHashes": {
                name: server.sha(Path(__file__).with_name(name))
                for name in artifacts.TOOL_FILES
            },
        }
        server.write_json(output / "manifest.json", manifest)
        operations, fingerprint = upload_job(
            executor, config, work, manifest, identifier, action="rollback"
        )
        result = wait_job(
            executor, config, operations, fingerprint, output, action="rollback"
        )
        server.require(result.get("rolledBack") is True, "回退未成功，必须人工核查")


def main(argv=None, *, executor_factory=Executor, repo=REPO):
    args = parse_args(argv)
    config_path = args.config or configuration.CONFIG_PATH
    if (
        args.config is None
        and not args.execute
        and not args.local_only
        and not config_path.exists()
    ):
        config_path = Path(__file__).with_name("config.example.toml")
        print("未配置 release.local.toml，以下仅为样例离线计划，不代表真实服务器配置。")
    config = configuration.load(config_path, executing=args.execute)
    if args.local_only:
        local_stages(args, config, repo)
        return 0
    executor = executor_factory(config, execute=args.execute)
    if not args.execute:
        plan(args, config, repo)
        return 0
    if args.command == "inspect":
        baseline = remote(executor, config, "protocol.describe(config,strict=False)")
        print(
            json.dumps(
                {
                    "production": baseline,
                    "diff": artifacts.diff_summary(
                        repo, baseline["commit"], artifacts.commit_id(repo, args.commit)
                    )
                    if baseline.get("commit")
                    else {"unavailable": "正式 staged.json 缺失，未猜测提交身份"},
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "status":
        expression = "protocol.latest_status(config)"
        scope = server.digest([config["ssh"], config["server"]["opsParent"]])
        requests = sorted(RECEIPTS.glob("*/request.json"), reverse=True)
        for path in requests:
            saved = json.loads(path.read_text())
            if saved.get("scope") == scope:
                expression = (
                    "protocol.status(protocol.operations_path(config,"
                    + repr(saved["operations"])
                    + "))"
                )
                break
        print(
            json.dumps(
                remote(executor, config, expression), ensure_ascii=False, indent=2
            )
        )
    elif args.command == "rollback":
        explicit_rollback(args, config, executor)
    else:
        publish(args, config, repo, executor)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        configuration.ConfigError,
        server.ReleaseError,
        OSError,
        subprocess.SubprocessError,
        ValueError,
    ) as error:
        print(
            f"发布停止：{error if isinstance(error, (configuration.ConfigError, server.ReleaseError)) else type(error).__name__}",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
