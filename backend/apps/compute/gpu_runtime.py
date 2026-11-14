"""Configured GPU execution for published operators, using the existing queue."""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import tomllib

from django.conf import settings

from apps.core.file_evidence import file_identity, read_receipt, write_receipt
from apps.core.storage import app_path
from apps.projects.context import selected_project_id
from .packages import ComputeError

RUNTIME = "python-geospatial-gpu-v1"
PACKAGES = ("torch", "numpy", "scipy", "GDAL", "Pillow", "tqdm", "pyproj")
_LOCK = threading.RLock()
_ENVIRONMENTS = {}


@dataclass(frozen=True)
class GPUProfile:
    interpreter: str
    asset_root: str
    gpu_ids: tuple[int, ...]
    memory_mb: int
    timeout_seconds: int
    max_band_pixels: int
    proj_data: str
    gdal_data: str
    lease_root: str
    busy_memory_mb: int


def configured(manifest, project_id=None):
    with settings.PROJECT_CONFIG.config_path.open("rb") as stream:
        compute = tomllib.load(stream).get("compute", {})
    raw = compute.get("gpu", {})
    selected = selected_project_id() if project_id is None else project_id
    if (
        compute.get("mode") != "native"
        or not raw.get("enabled")
        or selected not in raw.get("project_ids", [])
        or manifest.get("identifier") not in raw.get("allowed_algorithms", [])
    ):
        raise ComputeError("当前项目未配置该模型的GPU执行权限", 403)
    gpu_ids = raw.get("gpu_ids", [])
    if (
        not gpu_ids
        or len(set(gpu_ids)) != len(gpu_ids)
        or any(type(i) is not int or not 0 <= i < 32 for i in gpu_ids)
    ):
        raise ComputeError("GPU执行配置缺少有效设备", 503)
    paths = {
        key: str(raw.get(key, ""))
        for key in ["interpreter", "asset_root", "proj_data", "gdal_data", "lease_root"]
    }
    if any(not Path(value).is_absolute() for value in paths.values()):
        raise ComputeError("GPU运行路径配置无效", 503)
    values = {}
    for key, default, maximum in [
        ("memory_mb", 16384, 65536),
        ("timeout_seconds", 1800, 7200),
        ("max_band_pixels", 150000000, 500000000),
        ("busy_memory_mb", 1024, 65536),
    ]:
        value = raw.get(key, default)
        if type(value) is not int or not 1 <= value <= maximum:
            raise ComputeError("GPU资源预算配置无效", 503)
        values[key] = value
    if (
        not Path(paths["interpreter"]).is_file()
        or not (Path(paths["proj_data"]) / "proj.db").is_file()
    ):
        raise ComputeError("GPU解释器或投影数据库尚未就绪", 503)
    return GPUProfile(**paths, gpu_ids=tuple(gpu_ids), **values)


def _asset_digest(path, expected=None):
    if path.is_symlink() or not path.is_file():
        raise ComputeError("模型资产缺失或路径异常", 503)
    identity = list(file_identity(path.stat()))
    key = hashlib.sha256(str(path).encode()).hexdigest()
    receipt = app_path("cache", "gpu-assets", key + ".json")
    value = read_receipt(receipt, "gpu-asset-v1")
    if not value or value.get("identity") != identity or value.get("path") != str(path):
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if list(file_identity(path.stat())) != identity:
            raise ComputeError("模型资产在校验时发生变化", 409)
        value = {"path": str(path), "identity": identity, "sha256": digest}
        try:
            write_receipt(receipt, value, "gpu-asset-v1")
        except OSError:
            pass
    if expected is not None and value["sha256"] != expected:
        raise ComputeError("模型资产与登记摘要不一致", 409)
    return value["sha256"]


def environment(interpreter):
    with _LOCK:
        previous = _ENVIRONMENTS.get(interpreter)
        if previous:
            try:
                if all(
                    list(file_identity(Path(p).stat())) == identity
                    for p, identity in previous["files"].items()
                ):
                    return previous["value"]
            except OSError:
                pass
        source = """
import importlib.metadata as m,json,pathlib,sys
names=set(PACKAGES)
for distribution in m.distributions():
 name=distribution.metadata.get("Name", "")
 if name.lower().startswith("nvidia-") or name.lower()=="triton":names.add(name)
versions={};files=[str(pathlib.Path(sys.executable)),str(pathlib.Path(sys.prefix)/'lib')]
for name in names:
 d=m.distribution(name);versions[name]=d.version
 for file in d.files or []:
  text=str(file)
  if text.endswith('.dist-info/METADATA') or ('.so' in text) and (name!='torch' or '/_C.' in text):files.append(str(d.locate_file(file)))
print(json.dumps({'python':sys.version.split()[0],'packages':versions,'files':files}))
""".replace("PACKAGES", repr(PACKAGES))
        try:
            result = subprocess.run(
                [interpreter, "-I", "-c", source],
                capture_output=True,
                text=True,
                check=True,
                timeout=20,
            )
            value = json.loads(result.stdout)
            files = {
                p: list(file_identity(Path(p).stat()))
                for p in value.pop("files")
                if Path(p).exists()
            }
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            raise ComputeError("GPU运行环境缺少登记的科学计算依赖", 503) from error
        if len(_ENVIRONMENTS) >= 8:
            _ENVIRONMENTS.clear()
        value["files"] = files
        _ENVIRONMENTS[interpreter] = {"value": value, "files": files}
        return value


def binding(manifest, project_id=None):
    profile = configured(manifest, project_id)
    root = Path(profile.asset_root)
    path = root / "models/model_manifest.json"
    if root.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ComputeError("模型资产清单尚未就绪", 503)
    document = json.loads(path.read_text())
    assets = {}
    for item in document.get("weights", []):
        name = item.get("file", "")
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}\.pth", name) or not re.fullmatch(
            r"[a-f0-9]{64}", item.get("sha256", "")
        ):
            raise ComputeError("模型资产清单无效", 503)
        assets[name] = _asset_digest(root / "models" / name, item["sha256"])
    if len(assets) != 5:
        raise ComputeError("模型资产清单缺少类别", 503)
    for name in [
        "config/models.json",
        "config/postprocess.json",
        "models/model_manifest.json",
    ]:
        assets[name] = _asset_digest(root / name)
    identity = {
        "runtime": RUNTIME,
        "projDatabase": _asset_digest(Path(profile.proj_data) / "proj.db"),
        "environment": environment(profile.interpreter),
        "assets": assets,
        "profile": profile.__dict__,
    }
    digest = (
        "sha256:"
        + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    )
    return profile, {
        "ready": True,
        "id": RUNTIME,
        "name": "地理模型GPU执行环境",
        "imageDigest": digest,
        "detail": "GPU推理环境与模型资产就绪",
        "packages": identity["environment"]["packages"],
    }


def inspect(manifest, project_id=None):
    try:
        return binding(manifest, project_id)[1]
    except (ComputeError, OSError, ValueError, KeyError):
        return {
            "ready": False,
            "id": RUNTIME,
            "name": "地理模型GPU执行环境",
            "imageDigest": "",
            "detail": "GPU执行配置、模型资产或依赖尚未就绪",
        }


def require_binding(task):
    profile, state = binding(task.version.manifest, task.project_tag_id)
    if state["imageDigest"] != task.version.runtime_digest:
        raise ComputeError("GPU环境或模型资产已变化，请重新试运行并发布版本", 409)
    return profile, state


@contextmanager
def lease(profile):
    import fcntl

    try:
        output = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,uuid,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout
        rows = {
            int(parts[0]): (parts[1].strip(), int(parts[2]))
            for line in output.splitlines()
            if len(parts := line.split(",")) == 3
        }
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise ComputeError("GPU设备状态暂不可用", 503) from error
    for index in profile.gpu_ids:
        if index not in rows:
            continue
        uuid, used = rows[index]
        if used > profile.busy_memory_mb or not re.fullmatch(
            r"GPU-[a-fA-F0-9-]{8,64}", uuid
        ):
            continue
        path = Path(profile.lease_root) / (uuid + ".lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            continue
        try:
            yield uuid
        finally:
            handle.close()
        return
    raise ComputeError("已配置GPU正在使用，请等待资源释放后继续", 503)


def resident_bytes(pid):
    pending = [pid]
    seen = set()
    total = 0
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        try:
            root = Path("/proc") / str(current)
            values = (root / "statm").read_text().split()
            total += int(values[1]) * os.sysconf("SC_PAGE_SIZE")
            children = root / "task" / str(current) / "children"
            pending.extend(int(p) for p in children.read_text().split())
        except (OSError, ValueError, IndexError):
            pass
    return total


def clean_stage_caches(cutoff):
    """Remove only expired task scratch; active retries retain their stages."""
    import shutil
    from .models import ComputeTask

    root = app_path("projects")
    directories = list(root.glob("*/cache/landcover/*/*")) if root.is_dir() else []
    if not directories:
        return
    active = ComputeTask._base_manager.filter(
        status__in=["queued", "validating", "running", "cancelling"]
    )
    protected = {
        str(identity)
        for pair in active.values_list("pk", "retry_of_id")
        for identity in pair
        if identity
    }
    for directory in directories:
        if (
            directory.name not in protected
            and directory.is_dir()
            and directory.resolve() == directory.absolute()
            and directory.stat().st_mtime < cutoff
        ):
            shutil.rmtree(directory)
