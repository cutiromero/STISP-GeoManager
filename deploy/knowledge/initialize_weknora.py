"""Provision isolated WeKnora API credentials and existing local model endpoints.

Run on Linux after placing the reviewed binary at ROOT/WeKnora-lite. Credentials
are generated into private files, never accepted from the browser or printed.
"""

import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import urllib.request

from ensure_weknora import ensure


def save_secret(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.touch(mode=0o600, exist_ok=True)
    temporary.chmod(0o600)
    temporary.write_text(json.dumps(value))
    temporary.replace(path)


def request(port, path, body=None, token=None, key=None):
    headers = {"Content-Type": "application/json", "Accept-Language": "zh-CN"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if key:
        headers["X-API-Key"] = key
    payload = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=payload, headers=headers
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=30) as response:
        data = json.load(response)
    return (
        data.get("data", data) if isinstance(data, dict) and "success" in data else data
    )


def initialize(root, source, label, embedding_env):
    home = root / label
    if home.is_symlink():
        raise RuntimeError("Service home must be a real directory")
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ("config", "migrations"):
        if not (home / name).exists():
            shutil.copytree(source / name, home / name)
    port = 19020 if label == "production" else 19021
    config = home / "config/config.yaml"
    content = config.read_text()
    content = content.replace("port: 8080", f"port: {port}", 1)
    content = content.replace('host: "0.0.0.0"', 'host: "127.0.0.1"', 1)
    if f"port: {port}" not in content or 'host: "127.0.0.1"' not in content:
        raise RuntimeError("Private listen configuration must be reviewed")
    config.write_text(content)
    (home / "data").mkdir(mode=0o700, exist_ok=True)
    path = home / "secrets.json"
    if path.exists():
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise RuntimeError("Secret file must be private and regular")
        secret = json.loads(path.read_text())
    else:
        secret = {
            "password": "S9" + secrets.token_hex(14),
            "jwt_secret": secrets.token_hex(32),
            "aes_key": secrets.token_hex(16),
        }
        save_secret(path, secret)
    ensure(root, label)
    email = f"geomanager-{label}@weknora.local"
    if not secret.get("registered"):
        request(
            port,
            "/api/v1/auth/register",
            {
                "username": "STISP " + label,
                "email": email,
                "password": secret["password"],
            },
        )
        secret["registered"] = True
        save_secret(path, secret)
    if not secret.get("api_key"):
        login = request(
            port, "/api/v1/auth/login", {"email": email, "password": secret["password"]}
        )
        tenant = login["active_tenant"]["id"]
        data = request(
            port,
            f"/api/v1/tenants/{tenant}/api-keys",
            {
                "name": "GeoManager bridge",
                "full_access": True,
                "knowledge_base_ids": [],
                "capabilities": [],
            },
            token=login["token"],
        )
        # `token` is the usable secret. Upstream `api_key` is encrypted storage.
        secret.update(api_key=data["token"], tenant_id=tenant, key_version=2)
        save_secret(path, secret)
        ensure(root, label, stop=True)
        ensure(root, label)
    key_file = home / "api-key"
    if key_file.is_symlink():
        raise RuntimeError("API key file must be regular")
    key_file.touch(mode=0o600, exist_ok=True)
    key_file.chmod(0o600)
    key_file.write_text(secret["api_key"])
    existing = request(port, "/api/v1/models", key=secret["api_key"])
    if isinstance(existing, dict):
        existing = existing.get("models", [])

    def model(name, kind, parameters):
        match = next(
            (
                item
                for item in existing
                if item["name"] == name and item["type"] == kind
            ),
            None,
        )
        if match:
            return match["id"]
        created = request(
            port,
            "/api/v1/models",
            {
                "name": name,
                "display_name": name,
                "type": kind,
                "source": "remote",
                "parameters": parameters,
            },
            key=secret["api_key"],
        )
        return created["id"]

    if embedding_env.is_symlink() or embedding_env.stat().st_mode & 0o077:
        raise RuntimeError("Embedding environment file must be private and regular")
    embedding_key = next(
        line.split("=", 1)[1].strip().strip("'\"")
        for line in embedding_env.read_text().splitlines()
        if line.startswith("KNOWLEDGE_EMBEDDING_API_KEY=")
    )
    embed = model(
        "BAAI/bge-m3",
        "Embedding",
        {
            "base_url": "http://127.0.0.1:19010/v1",
            "provider": "generic",
            "api_key": embedding_key,
            "embedding_parameters": {
                "dimension": 1024,
                "truncate_prompt_tokens": 8192,
                "supports_dimension_override": False,
            },
            "max_concurrency": 2,
        },
    )
    chat = model(
        "Qwen/Qwen3.8-27B",
        "KnowledgeQA",
        {
            "base_url": "http://127.0.0.1:19000/v1",
            "provider": "generic",
            "api_key": "local",
            "context_window": 262144,
            "max_output_tokens": 4096,
            "max_concurrency": 2,
        },
    )
    receipt = {
        "label": label,
        "base_url": f"http://127.0.0.1:{port}",
        "api_key_file": str(key_file),
        "tenant_id": secret["tenant_id"],
        "embedding_model_id": embed,
        "chat_model_id": chat,
        "binary_sha256": hashlib.sha256(
            (root / "WeKnora-lite").read_bytes()
        ).hexdigest(),
    }
    (home / "bridge-config.json").write_text(json.dumps(receipt, indent=2))
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--label", choices=("production", "candidate"), default="production"
    )
    parser.add_argument("--embedding-env", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    with (root / "provision.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = initialize(
            root, args.source.resolve(strict=True), args.label, args.embedding_env
        )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
