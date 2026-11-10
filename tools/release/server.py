"""保留历史门禁的单机发布核心；由 release.py 调用。"""

from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import sqlite3
import subprocess
import tarfile
import time
import tomllib
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid

CONFIG_FILE = Path(__file__).with_name("remote-config.json")
DEFAULTS = {}
RUNTIME_INVARIANTS = {
    "drainSeconds": 900,
    "stopSeconds": 40,
    "healthSeconds": 120,
    "pollSeconds": 2,
    "backupSeconds": 180,
    "managementSeconds": 300,
    "httpSeconds": 10,
    "sqliteSeconds": 10,
    "heartbeatMaxAgeSeconds": 40,
    "startVerificationSeconds": 0.1,
    "stopPollSeconds": 0.2,
    "webThreads": 8,
    "webConnectionLimit": 100,
    "webChannelSeconds": 720,
    "productionPort": 6007,
    "protectedPorts": [19000, 19010, 19020],
}
ROLES = ("web", "compute_worker", "agent_worker", "workflow_worker")
ACTIVE = {
    "agent_agentrun": ("queued", "running"),
    "compute_computetask": ("queued", "validating", "running", "cancelling"),
    "compute_computeimport": ("queued", "running"),
    "agent_agentworkflow": ("queued", "running", "waiting_compute"),
}


class ReleaseError(RuntimeError):
    pass


class ManualIntervention(ReleaseError):
    pass


class SchemaChanged(ManualIntervention):
    pass


class UnknownStartedProcess(ManualIntervention):
    def __init__(self, pid):
        super().__init__(
            "A started child remains alive but its identity cannot be verified"
        )
        self.pid = pid


def require(condition, message):
    if not condition:
        raise ReleaseError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def entry_scripts(html):
    return re.findall(
        r"""(?:src|href)=["'](/static/[^"']+\.js(?:\?[^"']*)?)["']""", html
    )


def load_config(path):
    require(Path(path).is_file(), "Explicit runtime configuration is required")
    value = json.loads(Path(path).read_text())
    require(
        all(
            value.get(name) == expected for name, expected in RUNTIME_INVARIANTS.items()
        ),
        "Historical runtime limits must remain exact",
    )
    raw = tomllib.loads(Path(value["productionConfig"]).read_text())
    storage = raw["application"]["storage"]
    require(
        storage["app_data"] == value["appData"], "Production app-data identity differs"
    )
    require(
        storage["research_data_root"] == value["researchData"],
        "Production research-data identity differs",
    )
    require(
        value["deployLock"] != value["publishLock"],
        "The two publication locks must be distinct",
    )
    require(
        value["baseUrl"] == "http://127.0.0.1:6007",
        "Production checks must target the verified local 6007 listener",
    )
    return value


def database(config):
    return Path(config["appData"]) / "database/meta.db"


@contextmanager
def readonly_db(config):
    # Keep WAL visible. immutable=1 would incorrectly ignore live WAL contents.
    connection = sqlite3.connect(
        database(config).as_uri() + "?mode=ro",
        uri=True,
        timeout=config["sqliteSeconds"],
    )
    try:
        connection.execute("PRAGMA query_only=ON")
        yield connection
    finally:
        connection.close()


def active_counts(config):
    with readonly_db(config) as db:
        counts = {}
        for table, statuses in ACTIVE.items():
            placeholders = ",".join("?" for _ in statuses)
            counts[table] = db.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE status IN ({placeholders})',
                statuses,
            ).fetchone()[0]
        counts["parked_workflows"] = db.execute(
            "SELECT COUNT(*) FROM agent_agentworkflow WHERE status IN ('waiting_approval','paused')"
        ).fetchone()[0]
    return counts


def drain(config):
    deadline = time.monotonic() + config["drainSeconds"]
    while True:
        counts = active_counts(config)
        if not any(counts[table] for table in ACTIVE):
            return counts
        require(
            time.monotonic() < deadline,
            "Active work did not drain; no forced cancellation is allowed",
        )
        time.sleep(config["pollSeconds"])


def process(pid):
    root = Path("/proc") / str(pid)
    fields = (root / "stat").read_text().rsplit(")", 1)[1].split()
    return {
        "pid": int(pid),
        "startTicks": int(fields[19]),
        "cwd": os.readlink(root / "cwd"),
        "argv": (root / "cmdline").read_bytes().rstrip(b"\0").decode().split("\0"),
    }


def previous_role_root(config, role):
    return config.get("expectedRoleRoots", {}).get(role, config["expectedPreviousRoot"])


def role_of(item, config, app_root):
    args = item["argv"]
    if not args or args[0] != config["python"]:
        return None
    for role in ROLES:
        root = (
            previous_role_root(config, role)
            if app_root == config["expectedPreviousRoot"]
            else app_root
        )
        if item["cwd"] not in {root, str(Path(root) / "backend")}:
            continue
        if role == "web":
            expected = [
                config["python"],
                config["waitress"],
                "--host=0.0.0.0",
                "--port=6007",
                "--threads=8",
                "--connection-limit=100",
                "--channel-timeout=720",
                "geomanager.wsgi:application",
            ]
            if args == expected:
                return role
        else:
            prefix = [config["python"], str(Path(root) / "backend/manage.py"), role]
            if args in (prefix, [*prefix, "--config", config["productionConfig"]]):
                return role
    return None


def discover(config, app_root):
    found = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            item = process(entry.name)
            role = role_of(item, config, app_root)
            if role:
                require(
                    role not in found,
                    "Multiple production processes have the same role",
                )
                found[role] = item
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    require(
        set(found) == set(ROLES), "Production must have exactly four verified roles"
    )
    return found


def ensure_identity(item):
    try:
        require(
            process(item["pid"]) == item,
            "Process identity changed; refusing to signal PID",
        )
    except (FileNotFoundError, ProcessLookupError):
        raise ReleaseError("Expected process is absent") from None


def lock_owner(path):
    inode = Path(path).stat().st_ino
    matches = [
        line.split()
        for line in Path("/proc/locks").read_text().splitlines()
        if re.search(r":" + str(inode) + r"\s", line)
    ]
    return sorted({int(parts[4]) for parts in matches if parts[1] == "FLOCK"})


def worker_locks(config, processes):
    owners = {}
    for role in ROLES[1:]:
        path = Path(config["appData"]) / "cache" / (role.replace("_", "-") + ".lock")
        actual = lock_owner(path)
        require(
            actual == [processes[role]["pid"]],
            "Production worker lock has unexpected ownership",
        )
        owners[role] = actual
    return owners


def protected_listeners():
    value = subprocess.run(
        ["ss", "-lntpH"], check=True, capture_output=True, text=True
    ).stdout
    result = {}
    for port in (19000, 19010, 19020):
        lines = [
            line
            for line in value.splitlines()
            if re.search(r":" + str(port) + r"\s", line)
        ]
        require(len(lines) == 1, "Protected service listener is absent or ambiguous")
        pids = {int(pid) for pid in re.findall(r"pid=(\d+)", lines[0])}
        result[str(port)] = [
            {"pid": pid, "startTicks": process(pid)["startTicks"]}
            for pid in sorted(pids)
        ]
        require(result[str(port)], "Protected service has no visible process identity")
    return result


def launcher_root(config):
    text = Path(config["launcher"]).read_text()
    values = re.findall(r"^APP_ROOT=(\S+)\s*$", text, re.MULTILINE)
    require(len(values) == 1, "Launcher APP_ROOT assignment is not recognized")
    return values[0]


def static_identity(config):
    root = Path(config["appData"]) / "static"
    stat = root.lstat()
    return {
        "isLink": root.is_symlink(),
        "target": str(root.resolve()),
        "inode": stat.st_ino,
        "device": stat.st_dev,
        "ctimeNs": stat.st_ctime_ns,
    }


def inspect(config):
    root = launcher_root(config)
    processes = discover(config, root)
    return {
        "schema": 1,
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "appRoot": root,
        "launcherSha256": sha(config["launcher"]),
        "configSha256": sha(config["productionConfig"]),
        "processes": processes,
        "workerLockOwners": worker_locks(config, processes),
        "protectedListeners": protected_listeners(),
        "active": active_counts(config),
        "staticRoot": static_identity(config),
    }


@contextmanager
def publication_locks(config, manifest_sha):
    path = Path(config["deployLock"])
    token = {
        "pid": os.getpid(),
        "startTicks": process(os.getpid())["startTicks"],
        "manifestSha256": manifest_sha,
    }
    # An existing file, including a stale file, always needs manual investigation.
    deploy = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    inode = os.fstat(deploy).st_ino
    publish = None
    state = {"retainDeployLock": False}
    try:
        os.write(deploy, json.dumps(token).encode())
        os.fsync(deploy)
        publish = os.open(config["publishLock"], os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(publish, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield state
    finally:
        if publish is not None:
            os.close(publish)
        os.close(deploy)
        if (
            not state["retainDeployLock"]
            and path.exists()
            and path.stat().st_ino == inode
        ):
            path.unlink()


def safe_member(name):
    value = PurePosixPath(name)
    require(
        bool(name)
        and name != "."
        and "\\" not in name
        and not re.match(r"^[A-Za-z]:", name)
        and not any(ord(char) < 32 for char in name)
        and not value.is_absolute()
        and ".." not in value.parts
        and str(value) == name.rstrip("/"),
        "Unsafe archive member path",
    )
    require(
        value.parts
        and value.parts[0]
        not in {".git", ".runtime", ".claude", "CLAUDE.md", "app", "research", "data"},
        "Runtime/data/development-instruction paths cannot be packaged",
    )
    require(
        not any(part in {"node_modules", "__pycache__"} for part in value.parts),
        "Generated dependencies cannot be packaged",
    )
    require(
        value.suffix.lower() not in {".db", ".sqlite", ".sqlite3", ".pem", ".key"},
        "Database/key files cannot be packaged",
    )
    require(
        value.name not in {"app.toml", ".secret_key", "release.local.toml"},
        "Production configuration cannot be packaged",
    )
    return value


def extracted_file_mode(mode):
    """Freeze the regular-file permissions applied by tarfile's data filter."""
    mode &= 0o755
    if not mode & 0o100:
        mode &= ~0o111
    return mode | 0o600


def archive_files(path, expanded_limit):
    seen, total, files = set(), 0, {}
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            relative = str(safe_member(member.name))
            require(relative not in seen, "Duplicate archive member")
            seen.add(relative)
            require(
                member.isfile() or member.isdir(),
                "Symlinks and special archive members are forbidden",
            )
            require(not member.mode & 0o6000, "Privileged archive mode is forbidden")
            if member.isfile():
                total += member.size
                require(total <= expanded_limit, "Expanded archive exceeds size limit")
                with archive.extractfile(member) as stream:
                    files[relative] = {
                        "sha256": hashlib.file_digest(stream, "sha256").hexdigest(),
                        "bytes": member.size,
                        "mode": extracted_file_mode(member.mode),
                    }
    return files


def verify_tree(root, files):
    require(not Path(root).is_symlink(), "Staged code root cannot be a symlink")
    require(
        not any(path.is_symlink() for path in Path(root).rglob("*")),
        "Staged code cannot contain symlinks",
    )
    for name, expected in files.items():
        path = Path(root) / name
        require(
            path.is_file() and not path.is_symlink(), "Staged package file is missing"
        )
        require(
            path.stat().st_size == expected["bytes"]
            and path.stat().st_mode & 0o777 == expected["mode"]
            and sha(path) == expected["sha256"],
            "Staged package file differs from manifest",
        )
    extras = {
        str(path.relative_to(root))
        for path in Path(root).rglob("*")
        if path.is_file()
        and ".runtime" not in path.relative_to(root).parts
        and "__pycache__" not in path.relative_to(root).parts
    } - set(files)
    require(not extras, "Staged code contains files outside frozen manifest")


def load_release(config, manifest_path, expected_sha):
    require(
        re.fullmatch(r"[a-f0-9]{64}", expected_sha or ""),
        "A separately verified manifest SHA-256 is required",
    )
    require(sha(manifest_path) == expected_sha, "Frozen manifest fingerprint differs")
    value = json.loads(Path(manifest_path).read_text())
    require(
        value.get("schema") == 1
        and re.fullmatch(r"[a-f0-9]{40}", value.get("commit", "")),
        "Invalid frozen release identity",
    )
    require(
        value["baseline"]["appRoot"] == config["expectedPreviousRoot"],
        "Unexpected previous release",
    )
    require(
        value["baseline"]["launcherSha256"] == config["expectedLauncherSha256"],
        "Unexpected previous launcher",
    )
    require(
        value["noSchemaChanges"] is True,
        "This tool only permits a release without migration changes",
    )
    require(
        value["releaseToolSha256"] == sha(__file__),
        "Release tool differs from the reviewed frozen tool",
    )
    root = Path(value["releaseDir"])
    require(
        root.parent == Path(config["releaseParent"])
        and root.name.startswith("geomanager-release-"),
        "Release directory is outside the allowed new namespace",
    )
    require(
        value["appRoot"] == str(root / "code"),
        "Release code must be inside its new release directory",
    )
    package = Path(manifest_path).parent / value["package"]["file"]
    require(
        Path(value["package"]["file"]).name == value["package"]["file"],
        "Package must be a sibling basename",
    )
    require(
        package.stat().st_size
        == value["package"]["bytes"]
        <= config["maxArchiveBytes"],
        "Frozen package size differs",
    )
    require(
        sha(package) == value["package"]["sha256"], "Frozen package SHA-256 differs"
    )
    require(
        archive_files(package, config["maxExpandedBytes"]) == value["files"],
        "Archive content differs from frozen manifest",
    )
    fast = value.get("mode") == "fast"
    if fast:
        require(
            value.get("scientificOperatorsUnchanged") is True,
            "Fast releases cannot change scientific operators",
        )
        require(
            value.get("ancestorVerified") is True,
            "Fast releases require a verified production ancestor",
        )
    receipt = value["preflightAcceptance" if fast else "candidateAcceptance"]
    require(
        receipt.get("accepted") is True
        and receipt.get("commit") == value["commit"]
        and receipt.get("archiveSha256") == value["package"]["sha256"]
        and receipt.get("version") == value["version"],
        "Acceptance does not match this exact package",
    )
    require(
        isinstance(receipt.get("checks"), dict)
        and receipt["checks"]
        and all(value is True for value in receipt["checks"].values()),
        "Acceptance checks are missing or incomplete",
    )
    return value, package


def environment(config, app_root):
    return {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "geomanager.settings",
        "PYTHONPATH": str(Path(app_root) / "backend"),
        "PROJ_DATA": config["projData"],
        "GDAL_DATA": config["gdalData"],
    }


def manage(config, root, args, log):
    with Path(log).open("wb") as stream:
        os.chmod(log, 0o600)
        done = subprocess.run(
            [
                config["python"],
                str(Path(root) / "backend/manage.py"),
                *args,
                "--config",
                config["productionConfig"],
            ],
            cwd=root,
            env=environment(config, root),
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=config["managementSeconds"],
        )
    require(
        done.returncode == 0,
        "Management command failed; inspect its private release output",
    )
    return Path(log).read_text()


def migration_map(root):
    return {
        str(path.relative_to(root)): sha(path)
        for path in Path(root).glob("backend/apps/*/migrations/*.py")
    }


def migration_gate(config, release):
    require(
        migration_map(release["appRoot"])
        == migration_map(release["baseline"]["appRoot"]),
        "Migration sources differ; a separate schema release procedure is required",
    )
    for label, root in (
        ("old", release["baseline"]["appRoot"]),
        ("new", release["appRoot"]),
    ):
        text = manage(
            config,
            root,
            ["showmigrations", "--plan"],
            Path(release["releaseDir"]) / ("showmigrations-" + label + ".private.txt"),
        )
        require(
            "[X]" in text and "[ ]" not in text,
            "Production has unapplied or unrecognized migrations",
        )
    manage(
        config,
        release["appRoot"],
        ["makemigrations", "--check", "--dry-run"],
        Path(release["releaseDir"]) / "model-schema-check.private.txt",
    )


def baseline_gate(config, release):
    current = inspect(config)
    for key in (
        "appRoot",
        "launcherSha256",
        "configSha256",
        "processes",
        "workerLockOwners",
        "protectedListeners",
        "staticRoot",
    ):
        require(
            current[key] == release["baseline"][key],
            "Production identity differs from frozen baseline: " + key,
        )
    return current


def disk_gate(config, directory, required_bytes):
    require(
        shutil.disk_usage(directory).free
        >= required_bytes + config["minimumFreeBytes"],
        "Insufficient free disk space for release data and safety reserve",
    )


def directory_bytes(directory):
    return sum(
        path.stat().st_size
        for path in Path(directory).rglob("*")
        if path.is_file() and not path.is_symlink()
    )


def database_bytes(config):
    with readonly_db(config) as db:
        return (
            db.execute("PRAGMA page_count").fetchone()[0]
            * db.execute("PRAGMA page_size").fetchone()[0]
        )


def schema_version(config):
    with readonly_db(config) as db:
        return db.execute("PRAGMA schema_version").fetchone()[0]


def unchanged_schema(config, expected):
    try:
        current = schema_version(config)
    except Exception:
        raise SchemaChanged("Database schema identity is unavailable") from None
    if current != expected:
        raise SchemaChanged("Unexpected schema mutation")


def stage(config, release, package):
    root = Path(release["releaseDir"])
    disk_gate(
        config, root.parent, sum(item["bytes"] for item in release["files"].values())
    )
    root.mkdir(mode=0o700)  # existing directories never get reused or overwritten
    code = Path(release["appRoot"])
    code.mkdir(mode=0o700)
    try:
        with tarfile.open(package, "r:gz") as archive:
            archive.extractall(code, filter="data")
        verify_tree(code, release["files"])
        runtime = code / ".runtime"
        runtime.mkdir(mode=0o700)
        (runtime / "config-path").write_text(config["productionConfig"])
        os.chmod(runtime / "config-path", 0o600)
        baseline_gate(config, release)
        migration_gate(config, release)
        write_json(
            root / "staged.json",
            {
                "commit": release["commit"],
                "filesDigest": digest(release["files"]),
                "at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except BaseException:
        write_json(
            root / "stage-failed.json",
            {"failed": True, "at": datetime.now(timezone.utc).isoformat()},
        )
        raise


def backup_database(config, path):
    deadline = time.monotonic() + config["backupSeconds"]
    with readonly_db(config) as source, closing(sqlite3.connect(path)) as target:

        def progress(*args):
            require(time.monotonic() < deadline, "SQLite online backup timed out")

        source.backup(target, pages=512, progress=progress)
        require(
            target.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
            "SQLite backup integrity check failed",
        )
    os.chmod(path, 0o600)


def backup(config, directory):
    directory.mkdir(mode=0o700)
    shutil.copy2(config["productionConfig"], directory / "app.toml")
    shutil.copy2(config["launcher"], directory / "launcher.sh")
    os.chmod(directory / "app.toml", 0o600)
    os.chmod(directory / "launcher.sh", 0o700)
    static = Path(config["appData"]) / "static"
    require(
        static.is_dir()
        and (
            not static.is_symlink()
            or str(static.resolve()) == config.get("expectedStaticLinkTarget")
        ),
        "Production static root or exact link target differs",
    )
    shutil.copytree(static, directory / "static", symlinks=True)
    backup_database(config, directory / "meta.db")
    write_json(
        directory / "hashes.json",
        {
            name: sha(directory / name)
            for name in ("app.toml", "launcher.sh", "meta.db")
        },
    )


def stop(config, item):
    ensure_identity(item)
    os.kill(item["pid"], signal.SIGTERM)
    deadline = time.monotonic() + config["stopSeconds"]
    while time.monotonic() < deadline:
        try:
            if process(item["pid"])["startTicks"] != item["startTicks"]:
                return
        except (FileNotFoundError, ProcessLookupError):
            return
        time.sleep(config["stopPollSeconds"])
    raise ReleaseError("Process did not stop gracefully; SIGKILL is forbidden")


def read_environment(item):
    ensure_identity(item)
    return dict(
        part.decode().split("=", 1)
        for part in (Path("/proc") / str(item["pid"]) / "environ")
        .read_bytes()
        .split(b"\0")
        if part
    )


def start(config, templates, environments, app_root, roles=ROLES, journal=None):
    result = {} if journal is None else journal
    for role in roles:
        template = templates[role]
        previous_root = previous_role_root(config, role)
        target_root = (
            previous_root if app_root == config["expectedPreviousRoot"] else app_root
        )
        relative_cwd = Path(template["cwd"]).relative_to(previous_root)
        target_cwd = str(Path(target_root) / relative_cwd)
        argv = [part.replace(previous_root, target_root) for part in template["argv"]]
        env = {
            **environments[role],
            "PYTHONPATH": str(Path(target_root) / "backend"),
            "DJANGO_SETTINGS_MODULE": "geomanager.settings",
        }
        name = "waitress-6007" if role == "web" else role.replace("_", "-")
        with (Path(config["logDir"]) / (name + ".log")).open("ab") as output:
            child = subprocess.Popen(
                argv,
                cwd=target_cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                close_fds=True,
                start_new_session=True,
            )
        try:
            time.sleep(config["startVerificationSeconds"])
            item = process(child.pid)
        except BaseException:
            if child.poll() is None:
                raise UnknownStartedProcess(child.pid) from None
            raise ReleaseError(
                "Started process exited before identity verification"
            ) from None
        result[role] = item
        require(
            role_of(item, config, app_root) == role, "Started process identity differs"
        )
        (Path(config["logDir"]) / (name + ".pid")).write_text(str(child.pid) + "\n")
    return result


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def http(config, path):
    request = Request(config["baseUrl"] + path, headers={"Accept-Encoding": "identity"})
    with build_opener(ProxyHandler({}), NoRedirect()).open(
        request, timeout=config["httpSeconds"]
    ) as response:
        require(response.status == 200, "HTTP gate requires status 200")
        if path.startswith("/static/") and path.split("?", 1)[0].endswith(".js"):
            require(
                response.headers.get_content_type()
                in {
                    "application/javascript",
                    "text/javascript",
                },
                "Static JavaScript Content-Type is invalid",
            )
        return response.read()


def gate(config, release, processes, started_at, old=False):
    for item in processes.values():
        ensure_identity(item)
    worker_locks(config, processes)
    require(
        protected_listeners() == release["baseline"]["protectedListeners"],
        "Protected service listener identity changed",
    )
    require(
        json.loads(http(config, config["healthPath"])).get("status") == "ok",
        "Health endpoint is not healthy",
    )
    html = http(config, "/").decode()
    assets = entry_scripts(html)
    require(bool(assets), "Homepage has no recognized static JavaScript")
    if not old:
        require(
            sorted(assets) == sorted(release["entryJavascript"]),
            "Homepage does not reference frozen frontend entry scripts",
        )
    for asset in assets:
        content = http(config, asset)
        require(len(content) > 0, "Static JavaScript is empty")
        if not old:
            relative = "frontend/dist/" + asset.split("?", 1)[0].removeprefix(
                "/static/"
            )
            require(
                hashlib.sha256(content).hexdigest()
                == release["files"][relative]["sha256"],
                "Served JavaScript fingerprint differs",
            )
        else:
            original = (
                Path(release["baseline"]["appRoot"])
                / "frontend/dist"
                / asset.split("?", 1)[0].removeprefix("/static/")
            )
            require(
                original.is_file()
                and hashlib.sha256(content).hexdigest() == sha(original),
                "Rolled-back JavaScript differs from the old code",
            )
    with readonly_db(config) as db:
        timestamps = [
            db.execute(
                "SELECT heartbeat FROM agent_agentruntime WHERE name=?", ("worker",)
            ).fetchone(),
            db.execute(
                "SELECT heartbeat FROM agent_agentruntime WHERE name=?",
                ("workflow-worker",),
            ).fetchone(),
            db.execute(
                "SELECT heartbeat FROM compute_runtimelease WHERE name=?", ("worker",)
            ).fetchone(),
        ]
    for value in timestamps:
        require(value and value[0], "Worker heartbeat is missing")
        moment = datetime.fromisoformat(value[0].replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        require(
            moment.timestamp() >= started_at - 1
            and time.time() - moment.timestamp() < config["heartbeatMaxAgeSeconds"],
            "Worker heartbeat is stale or predates this launch",
        )


def wait_gate(config, release, processes, started_at, old=False):
    deadline, last = time.monotonic() + config["healthSeconds"], None
    while time.monotonic() < deadline:
        try:
            gate(config, release, processes, started_at, old)
            return
        except Exception as error:
            last = type(error).__name__
            time.sleep(config["pollSeconds"])
    raise ReleaseError("Hard HTTP/process/heartbeat/static gate failed: " + str(last))


def replace_launcher(config, content):
    path = Path(config["launcher"])
    temporary = path.with_name(path.name + ".new-" + uuid.uuid4().hex)
    temporary.write_bytes(content)
    temporary.chmod(0o700)
    os.replace(temporary, path)


def operator_bootstrap(config, release, rollback=False):
    if not config.get("postMigrationScript"):
        return  # Code-only unification leaves published scientific operators unchanged.
    script = Path(config["postMigrationScript"])
    require(
        sha(script) == config["postMigrationSha256"],
        "Operator bootstrap identity differs",
    )
    log = Path(release["releaseDir"]) / (
        "operator-rollback.private.txt"
        if rollback
        else "operator-bootstrap.private.txt"
    )
    with log.open("wb") as stream:
        os.chmod(log, 0o600)
        done = subprocess.run(
            [config["python"], str(script), *(["--rollback"] if rollback else [])],
            cwd=release["appRoot"],
            env=environment(config, release["appRoot"]),
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=config["managementSeconds"],
        )
    require(
        done.returncode == 0,
        "Prospect operator bootstrap failed; review its private receipt",
    )


def cutover(config, release, lock_state):
    root = Path(release["releaseDir"])
    require((root / "staged.json").is_file(), "Release has not been staged")
    require(
        json.loads((root / "staged.json").read_text())["filesDigest"]
        == digest(release["files"]),
        "Staging receipt differs",
    )
    verify_tree(release["appRoot"], release["files"])
    require(
        (Path(release["appRoot"]) / ".runtime/config-path").read_text()
        == config["productionConfig"],
        "Staged configuration pointer is not production",
    )
    baseline = baseline_gate(config, release)
    migration_gate(config, release)
    drain(config)  # keep the four old roles serving until the queue is quiet
    baseline_gate(config, release)
    old = baseline["processes"]
    environments = {role: read_environment(item) for role, item in old.items()}
    launcher_bytes = Path(config["launcher"]).read_bytes()
    backup_dir = root / ("production-backup-" + uuid.uuid4().hex[:8])
    static = Path(config["appData"]) / "static"
    static_bytes = directory_bytes(static)
    disk_gate(
        config,
        root,
        2 * database_bytes(config)
        + static_bytes
        + max(static_bytes, directory_bytes(Path(release["appRoot"]) / "frontend/dist"))
        + config["staticPreparationAllowanceBytes"],
    )
    backup(config, backup_dir)
    # Preserve complete public dependency sets before changing the active static tree.
    sources = [
        Path(config["expectedPreviousRoot"]) / "frontend/dist",
        Path(release["appRoot"]) / "frontend/dist",
    ]
    for historical in config.get("historicalFrontendSources", []):
        source = Path(historical)
        require(
            source.is_relative_to(Path(config["releaseParent"])),
            "Historical source escaped release parent",
        )
        sources.insert(0, source)
    for number, source in enumerate(sources):
        manage(
            config,
            release["appRoot"],
            ["archive_frontend_assets", "--source", str(source)],
            root / f"frontend-history-{number}.json",
        )
    old_static, prepared = root / "static-previous-active", root / "static-next"
    require(
        static.lstat().st_dev == root.stat().st_dev,
        "Static replacement requires a single filesystem",
    )
    # Build static into a new directory, without changing production settings or configuration.
    builder = (
        "import django;django.setup();from django.conf import settings;settings.STATIC_ROOT="
        + repr(str(prepared))
        + ";from django.core.management import call_command;call_command('collectstatic',interactive=False,clear=True,verbosity=0)"
    )
    with (root / "collectstatic.private.txt").open("wb") as output:
        os.chmod(root / "collectstatic.private.txt", 0o600)
        outcome = subprocess.run(
            [config["python"], "-c", builder],
            cwd=release["appRoot"],
            env=environment(config, release["appRoot"]),
            stdout=output,
            stderr=subprocess.STDOUT,
            timeout=config["managementSeconds"],
        )
    require(outcome.returncode == 0 and prepared.is_dir(), "Static preparation failed")
    baseline_gate(config, release)
    disk_gate(config, root, database_bytes(config))
    stopped, launched, static_moved, launcher_changed = set(), {}, False, False
    bootstrap_attempted = False
    try:
        stop(config, old["web"])
        stopped.add("web")
        drain(config)  # no Web admission remains; consume races before stopping workers
        for role in ROLES[1:]:
            stop(config, old[role])
            stopped.add(role)
        require(
            not any(active_counts(config)[table] for table in ACTIVE),
            "Work appeared after final drain",
        )
        backup_database(config, backup_dir / "meta-quiesced.db")
        write_json(
            backup_dir / "quiesced-sha256.json",
            {"meta-quiesced.db": sha(backup_dir / "meta-quiesced.db")},
        )
        schema_before = schema_version(config)
        write_json(
            root / "rollback-context.json",
            {
                "schemaVersion": schema_before,
                "backup": str(backup_dir),
                "previousRoot": release["baseline"]["appRoot"],
                "previousLauncherSha256": release["baseline"]["launcherSha256"],
            },
        )
        try:
            manage(
                config,
                release["appRoot"],
                ["migrate", "--noinput"],
                root / "migrate.private.txt",
            )
            migration_gate(config, release)
        finally:
            # Even a failed migration command must not restart old code against an
            # unexpected schema. No database file is ever restored by this tool.
            unchanged_schema(config, schema_before)
        bootstrap_attempted = True
        operator_bootstrap(config, release)
        unchanged_schema(config, schema_before)
        os.replace(static, old_static)
        static_moved = True
        os.replace(prepared, static)
        patched, count = re.subn(
            rb"(?m)^APP_ROOT=\S+[^\S\n]*$",
            b"APP_ROOT=" + release["appRoot"].encode(),
            launcher_bytes,
        )
        require(count == 1, "Launcher patch did not change exactly one APP_ROOT")
        patched, worker_count = re.subn(
            rb"(?m)^WORKER_APP_ROOT=\S+[^\S\n]*$",
            b"WORKER_APP_ROOT=" + release["appRoot"].encode(),
            patched,
        )
        require(
            worker_count == 1,
            "Launcher patch did not change exactly one WORKER_APP_ROOT",
        )
        require(
            re.findall(rb"(?m)^(?:WORKER_)?APP_ROOT=(\S+)", patched)
            == [release["appRoot"].encode()] * 2,
            "Launcher roles must use the same frozen code root",
        )
        replace_launcher(config, patched)
        launcher_changed = True
        started_at = time.time()
        for role in ("compute_worker", "agent_worker", "workflow_worker", "web"):
            start(
                config, old, environments, release["appRoot"], (role,), journal=launched
            )
        wait_gate(config, release, launched, started_at)
        write_json(
            root / "production-accepted.json",
            {
                "accepted": True,
                "commit": release["commit"],
                "version": release["version"],
                "at": datetime.now(timezone.utc).isoformat(),
                "processes": launched,
                "backup": str(backup_dir),
                "databaseRestored": False,
            },
        )
    except BaseException as error:
        if isinstance(error, ManualIntervention):
            lock_state["retainDeployLock"] = True
            write_json(
                root / "manual-intervention-required.json",
                {
                    "reasonType": type(error).__name__,
                    "retainDeployLock": True,
                    "databaseRestored": False,
                    "rolesStopped": sorted(stopped),
                    "knownStartedProcesses": launched,
                    "unverifiedChildPid": getattr(error, "pid", None),
                    "at": datetime.now(timezone.utc).isoformat(),
                },
            )
            raise ReleaseError(
                "Safe automatic recovery is unavailable; DEPLOY.lock is retained and no old role is restarted"
            ) from None
        try:
            if "web" in launched:
                stop(config, launched["web"])
                launched.pop("web")
            drain(config)
            for role, item in list(launched.items()):
                stop(config, item)
                launched.pop(role)
            if bootstrap_attempted:
                operator_bootstrap(config, release, rollback=True)
            if static_moved:
                if static.exists():
                    os.replace(static, root / "static-failed-new")
                os.replace(old_static, static)
            if launcher_changed:
                replace_launcher(config, launcher_bytes)
            resumed_at = time.time()
            restored = {role: item for role, item in old.items() if role not in stopped}
            for role in (*ROLES[1:], "web"):
                if role in stopped:
                    restored.update(
                        start(
                            config,
                            old,
                            environments,
                            release["baseline"]["appRoot"],
                            (role,),
                        )
                    )
            wait_gate(config, release, restored, resumed_at, old=True)
            write_json(
                root / "production-rolled-back.json",
                {
                    "rolledBack": True,
                    "reasonType": type(error).__name__,
                    "processes": restored,
                    "databaseRestored": False,
                    "at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except BaseException as rollback_error:
            lock_state["retainDeployLock"] = True
            write_json(
                root / "manual-intervention-required.json",
                {
                    "reasonType": type(error).__name__,
                    "rollbackErrorType": type(rollback_error).__name__,
                    "knownStartedProcesses": launched,
                    "unverifiedChildPid": getattr(rollback_error, "pid", None),
                    "retainDeployLock": True,
                    "databaseRestored": False,
                    "at": datetime.now(timezone.utc).isoformat(),
                },
            )
            raise ReleaseError(
                "Rollback could not finish safely; DEPLOY.lock retained for manual investigation"
            ) from None
        raise ReleaseError(
            "Release failed its hard gate; code/launcher/static rolled back using the current production database"
        ) from None
