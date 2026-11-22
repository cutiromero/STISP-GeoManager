"""Local lifecycle for the independently running MH-agent gateway."""

from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import secrets
import signal
import subprocess
import tempfile
import threading
import tomllib

from django.conf import settings
import yaml

logger = logging.getLogger(__name__)
PROFILE_DIRECTORY = "mh-agent"


def service_config(project):
    path = project.app_path("config", "mh-agent.toml")
    try:
        with path.open("rb") as source:
            value = tomllib.load(source)
    except FileNotFoundError:
        return None
    if value.get("enabled") is not True:
        return None
    for name in ("port", "model_port"):
        if type(value.get(name)) is not int or not 1024 <= value[name] <= 65535:
            raise ValueError(f"Invalid MH-agent {name}")
    if len({value["port"], value["model_port"], project.runtime.waitress_port}) != 3:
        raise ValueError("MH-agent, platform web and model ports must differ")
    if not Path(value.get("runtime", "")).is_absolute() or not value.get("model"):
        raise ValueError("MH-agent requires an absolute runtime and a model name")
    return value


def service_root(project):
    return project.app_path("config", PROFILE_DIRECTORY)


def atomic_private(path, content):
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as target:
        temp = Path(target.name)
        try:
            target.write(content)
            target.close()
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


def prepare(project, configuration):
    source = settings.PROGRAM_ROOT / "deploy/hermes"
    root = service_root(project)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    profile = root / "profile"
    profile.mkdir(mode=0o700, exist_ok=True)
    credentials_file = root / "credentials.json"
    if credentials_file.exists():
        credentials = json.loads(credentials_file.read_text(encoding="utf-8"))
    else:
        credentials = {
            name: secrets.token_hex(32) for name in ("gateway_key", "tool_key")
        }
    credentials["gateway_port"] = configuration["port"]
    atomic_private(credentials_file, json.dumps(credentials))
    plugin_name = "stisp-business-flows"
    plugin = profile / "plugins" / plugin_name
    plugin.mkdir(mode=0o700, parents=True, exist_ok=True)
    for filename in ("plugin.yaml", "__init__.py"):
        atomic_private(
            plugin / filename,
            (source / "plugin" / filename).read_text(encoding="utf-8"),
        )
    config = {
        "model": {
            "provider": "custom",
            "default": configuration["model"],
            "base_url": f"http://127.0.0.1:{configuration['model_port']}/v1",
            "api_mode": "chat_completions",
            **(
                {"context_length": configuration["context_length"]}
                if "context_length" in configuration
                else {}
            ),
        },
        "gateway": {
            "api_server": {
                "enabled": True,
                "host": "127.0.0.1",
                "port": configuration["port"],
                "model_name": "MH-agent",
                "max_concurrent_runs": 2,
            }
        },
        "agent": {"max_turns": 24, "disabled_toolsets": ["skill_manage"]},
        "platform_toolsets": {
            "api_server": [
                "skills",
                "clarify",
                "todo",
                "web",
                "stisp_business_flows",
                "stisp_project_data",
            ]
        },
        "web": {"backend": "keenable", "extract_char_limit": 8000},
        "plugins": {"enabled": [plugin_name]},
        "memory": {"memory_enabled": False, "user_profile_enabled": False},
        "skills": {
            "inline_shell": False,
            "template_vars": False,
            "project_discovery": False,
        },
    }
    atomic_private(profile / "config.yaml", yaml.safe_dump(config))
    environment = {
        name: os.environ[name]
        for name in (
            "PATH",
            "LANG",
            "LC_ALL",
            "TZ",
            "TERM",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
        )
        if name in os.environ
    }
    environment.update(
        {
            "HOME": str(root),
            "HERMES_HOME": str(profile),
            "HERMES_BUNDLED_SKILLS": str(source / "skills"),
            "API_SERVER_KEY": credentials["gateway_key"],
            "STISP_HERMES_TOOL_KEY": credentials["tool_key"],
            "STISP_HERMES_BACKEND_PORT": str(project.runtime.waitress_port),
            "STISP_HERMES_TOOL_CONTRACTS": str(
                Path(__file__).with_name("tool_contracts.json")
            ),
            "STISP_HERMES_TOOLSETS": str(source / "toolsets.json"),
        }
    )
    return profile, environment


def supervise(stop, configuration):
    project = settings.PROJECT_CONFIG
    command = [configuration["runtime"], "gateway", "run"]
    while not stop.is_set():
        try:
            profile, environment = prepare(project, configuration)
            log_path = project.app_path("logs", "mh-agent.log")
            log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with log_path.open("ab") as log:
                process = subprocess.Popen(
                    command,
                    cwd=profile,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            while process.poll() is None and not stop.wait(1):
                pass
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=24)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            elif not stop.is_set():
                logger.error(
                    "MH-agent gateway exited with status %s", process.returncode
                )
        except (OSError, ValueError):
            logger.exception("MH-agent gateway startup failed")
        stop.wait(8)


@contextmanager
def manage_gateway(stop, *, once=False):
    config = None if once else service_config(settings.PROJECT_CONFIG)
    thread = None
    if config:
        thread = threading.Thread(
            target=supervise,
            args=(stop, config),
            name="mh-agent-supervisor",
            daemon=True,
        )
        thread.start()
    try:
        yield
    finally:
        if thread:
            stop.set()
            thread.join(timeout=27)
