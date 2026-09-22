"""Download a verified Docker Hub base image using the existing Windows proxy.

No daemon, proxy listener or WSL network configuration is changed. The anonymous
registry token is sent via curl's stdin, never printed or stored in the archive.
"""
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
from urllib.parse import urlsplit
import winreg

root = Path(__file__).resolve().parents[1] / ".runtime" / "compute-base-image"
root.mkdir(parents=True, exist_ok=True)
with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
    proxy = winreg.QueryValueEx(key, "ProxyServer")[0]
assert proxy.startswith("127.0.0.1:") and proxy.rsplit(":", 1)[1].isdigit()
repo = "library/python"
base = f"https://registry-1.docker.io/v2/{repo}"
tag = "3.12-slim-bookworm"
token = ""


def fetch(url, target=None, accept=None):
    options = []
    if token:
        options.append(f'header = "Authorization: Bearer {token}"')
    if accept:
        options.append(f'header = "Accept: {accept}"')
    args = ["curl.exe", "--fail", "--silent", "--show-error", "--location",
            "--retry", "1", "--connect-timeout", "15", "--max-time", "60",
            "--proxy", "http://" + proxy, "--config", "-", url]
    if target:
        args += ["--output", str(target)]
    result = subprocess.run(args, input="\n".join(options).encode(),
                            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(f"Official image download failed from {urlsplit(url).hostname} (curl {result.returncode})")
    return result.stdout


def valid(data, digest):
    assert "sha256:" + hashlib.sha256(data).hexdigest() == digest, "Image digest mismatch"


print("Requesting official registry manifest", flush=True)
token = json.loads(fetch(f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull"))["token"]
accept = ",".join(["application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json",
                   "application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"])
index = json.loads(fetch(f"{base}/manifests/{tag}", accept=accept))
digest = next(m["digest"] for m in index["manifests"]
              if m["platform"]["architecture"] == "amd64" and m["platform"]["os"] == "linux")
manifest_bytes = fetch(f"{base}/manifests/{digest}", accept=accept)
valid(manifest_bytes, digest)
manifest = json.loads(manifest_bytes)
config_digest = manifest["config"]["digest"]
config_bytes = fetch(f"{base}/blobs/{config_digest}")
valid(config_bytes, config_digest)
config = json.loads(config_bytes)
layers = []
for number, spec in enumerate(manifest["layers"]):
    path = root / (spec["digest"].split(":")[1] + ".gz")
    if not path.exists() or path.stat().st_size != spec["size"]:
        print(f"Downloading official layer {number + 1}: {spec['size']} bytes", flush=True)
        fetch(f'{base}/blobs/{spec["digest"]}', target=path)
    with path.open("rb") as stream:
        assert "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest() == spec["digest"]
    unpacked = path.with_suffix(".tar")
    with gzip.open(path, "rb") as source, unpacked.open("wb") as output:
        while chunk := source.read(1024 * 1024):
            output.write(chunk)
    with unpacked.open("rb") as stream:
        assert "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest() == config["rootfs"]["diff_ids"][number]
    layers.append(unpacked)
    print(f"Verified official Python layer {number + 1}/{len(manifest['layers'])}", flush=True)

image = root / "python-3.12-slim-bookworm.tar"
with tarfile.open(image, "w") as archive:
    config_name = config_digest.split(":")[1] + ".json"
    entries = {
        config_name: config_bytes,
        "manifest.json": json.dumps([{"Config": config_name, "RepoTags": ["python:" + tag],
                                      "Layers": [p.name for p in layers]}]).encode(),
    }
    for name, data in entries.items():
        entry = tarfile.TarInfo(name)
        entry.size = len(data)
        archive.addfile(entry, io.BytesIO(data))
    for path in layers:
        archive.add(path, arcname=path.name)
(root / "provenance.json").write_text(json.dumps({"registry": "docker.io", "repository": repo,
    "tag": tag, "manifestDigest": digest, "configDigest": config_digest}, indent=2))
print(f"Verified base archive ready: {image}", flush=True)
