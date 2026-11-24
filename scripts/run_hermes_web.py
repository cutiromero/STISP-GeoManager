"""Prepare and start the pinned Hermes gateway for local GeoManager development."""

import getpass
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.request import urlopen

import yaml

# Configuration
ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_COMMIT = "0f602c5f6f18615632535251d62a2db74ce93b69"
UPSTREAM = ROOT.parent / ".runtime/hermes-agent-adaptation/upstream"
RUNTIME = ROOT / ".runtime/hermes-web"
PROFILE = RUNTIME / "profile"
GATEWAY_PORT = 18642
DJANGO_PORT = 8000
MODEL = "deepseek-v4-flash"
WEB_BACKEND = "keenable"


def prepare_upstream():
    if not (UPSTREAM / "uv.lock").is_file():
        UPSTREAM.parent.mkdir(parents=True, exist_ok=True)
        uri = f"https://api.github.com/repos/NousResearch/hermes-agent/tarball/{UPSTREAM_COMMIT}"
        with tempfile.TemporaryDirectory(dir=UPSTREAM.parent) as temp:
            directory = Path(temp)
            archive = directory / "hermes.tar.gz"
            with urlopen(uri, timeout=60) as source, archive.open("wb") as target:
                shutil.copyfileobj(source, target)
            with tarfile.open(archive) as source:
                source.extractall(directory, filter="data")
            (extracted,) = directory.glob("NousResearch-hermes-agent-*/")
            extracted.rename(UPSTREAM)
    command = UPSTREAM / ".venv/bin/hermes"
    if not command.is_file():
        subprocess.run(
            [
                "uv",
                "sync",
                "--frozen",
                "--no-dev",
                "--extra",
                "sms",
                "--python",
                sys.executable,
            ],
            cwd=UPSTREAM,
            check=True,
        )
    # This revision's API handler passes a removed keyword to native discovery.
    handler = UPSTREAM / "gateway/platforms/api_server.py"
    source = handler.read_text(encoding="utf-8")
    fixed = source.replace(
        "skip_disabled=False, include_editorial=True", "skip_disabled=False", 1
    )
    if source != fixed:
        handler.write_text(fixed, encoding="utf-8")
    return command


def prepare_profile():
    PROFILE.mkdir(parents=True, exist_ok=True, mode=0o700)
    credentials_file = RUNTIME / "credentials.json"
    try:
        with credentials_file.open(encoding="utf-8") as source:
            credentials = json.load(source)
    except FileNotFoundError:
        credentials = {
            "gateway_key": secrets.token_hex(32),
            "tool_key": secrets.token_hex(32),
            "gateway_port": GATEWAY_PORT,
        }
        fd = os.open(credentials_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            json.dump(credentials, target)
    plugin_name = "stisp-business-flows"
    shutil.copytree(
        ROOT / "deploy/hermes/plugin",
        PROFILE / "plugins" / plugin_name,
        dirs_exist_ok=True,
    )
    config = {
        "model": {"default": MODEL, "provider": "deepseek"},
        "gateway": {
            "api_server": {
                "enabled": True,
                "host": "127.0.0.1",
                "port": int(credentials["gateway_port"]),
                "max_concurrent_runs": 3,
            }
        },
        "agent": {"disabled_toolsets": ["skill_manage"]},
        "platform_toolsets": {
            "api_server": [
                "skills",
                "clarify",
                "todo",
                "web",
                "stisp_business_flows",
                "stisp_project_data",
                "stisp_research_compute",
            ]
        },
        "web": {"backend": WEB_BACKEND, "extract_char_limit": 8000},
        "plugins": {"enabled": [plugin_name]},
        "memory": {"memory_enabled": False, "user_profile_enabled": False},
        "skills": {
            "inline_shell": False,
            "template_vars": False,
            "project_discovery": False,
        },
    }
    (PROFILE / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    return credentials


def main():
    executable = prepare_upstream()
    credentials = prepare_profile()
    model_key = os.environ.get("DEEPSEEK_API_KEY") or getpass.getpass(
        "DeepSeek API key: "
    )
    if not model_key.strip():
        raise SystemExit("请输入 DeepSeek API 密钥")
    environment = {
        **os.environ,
        "HERMES_HOME": str(PROFILE),
        "HERMES_BUNDLED_SKILLS": str(ROOT / "deploy/hermes/skills"),
        "DEEPSEEK_API_KEY": model_key.strip(),
        "API_SERVER_KEY": credentials["gateway_key"],
        "STISP_HERMES_TOOL_KEY": credentials["tool_key"],
        "STISP_HERMES_BACKEND_PORT": str(DJANGO_PORT),
        "STISP_HERMES_TOOL_CONTRACTS": str(
            ROOT / "backend/apps/agent/tool_contracts.json"
        ),
        "STISP_HERMES_TOOLSETS": str(ROOT / "deploy/hermes/toolsets.json"),
    }
    os.chdir(tempfile.gettempdir())
    os.execve(executable, [str(executable), "gateway", "run"], environment)


if __name__ == "__main__":
    main()
