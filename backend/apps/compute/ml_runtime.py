"""Configured CPU model assets, bound to the existing native computation queue."""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import tomllib

from django.conf import settings
from apps.core.storage import app_path
from apps.projects.context import selected_project_id
from .config import config
from .gpu_runtime import _asset_digest
from .packages import ComputeError

RUNTIME = "python-geospatial-ml-v1"


@dataclass(frozen=True)
class MLProfile:
    interpreter: str
    asset_root: str
    model_file: str
    model_sha256: str
    memory_mb: int
    timeout_seconds: int
    max_band_pixels: int
    proj_data: str
    gdal_data: str


def configured(manifest, project_id=None):
    with settings.PROJECT_CONFIG.config_path.open("rb") as stream:
        raw = tomllib.load(stream).get("compute", {}).get("ml", {})
    project_id = selected_project_id() if project_id is None else project_id
    if (
        config().mode != "native"
        or not raw.get("enabled")
        or project_id not in raw.get("project_ids", [])
        or manifest.get("identifier") not in raw.get("allowed_algorithms", [])
    ):
        raise ComputeError("当前项目尚未配置该模型的计算权限", 403)
    paths = {
        key: str(raw.get(key, "")) for key in ("asset_root", "proj_data", "gdal_data")
    }
    if (
        any(not value or not Path(value).is_absolute() for value in paths.values())
        or not Path(paths["asset_root"]).is_dir()
    ):
        raise ComputeError("模型计算路径尚未配置", 503)
    name, checksum = raw.get("model_file", ""), raw.get("model_sha256", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.pkl", name) or not re.fullmatch(
        r"[a-f0-9]{64}", checksum
    ):
        raise ComputeError("模型资产清单无效", 503)
    values = {}
    for key, default, maximum in [
        ("memory_mb", 8192, 32768),
        ("timeout_seconds", 1800, 7200),
        ("max_band_pixels", 100000000, 100000000),
    ]:
        value = raw.get(key, default)
        if type(value) is not int or not 1 <= value <= maximum:
            raise ComputeError("模型资源预算无效", 503)
        values[key] = value
    if any(
        (port.get("raster") or {}).get("streaming")
        for port in manifest.get("inputs", [])
    ):
        seconds = raw.get("streaming_timeout_seconds", 7200)
        if type(seconds) is not int or not 1 <= seconds <= 7200:
            raise ComputeError("全域流式计算时限无效", 503)
        values["timeout_seconds"] = seconds
    return MLProfile(
        interpreter=config().interpreter,
        model_file=name,
        model_sha256=checksum,
        **paths,
        **values,
    )


def binding(manifest, project_id=None):
    profile = configured(manifest, project_id)
    asset = _asset_digest(
        Path(profile.asset_root) / profile.model_file, profile.model_sha256
    )
    packages = {}
    try:
        for name in (
            "scikit-learn",
            "joblib",
            "threadpoolctl",
            "numpy",
            "scipy",
            "rasterio",
            "pyproj",
        ):
            packages[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError as error:
        raise ComputeError("模型计算缺少依赖：" + str(error), 503) from error
    identity = {"profile": profile.__dict__, "packages": packages, "asset": asset}
    digest = (
        "sha256:"
        + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    )
    return profile, {
        "ready": True,
        "id": RUNTIME,
        "name": "地理模型CPU计算环境",
        "imageDigest": digest,
        "detail": "模型与现有计算环境就绪",
        "packages": packages,
    }


def inspect(manifest, project_id=None):
    try:
        return binding(manifest, project_id)[1]
    except (ComputeError, OSError, ValueError, KeyError):
        return {
            "ready": False,
            "id": RUNTIME,
            "name": "地理模型CPU计算环境",
            "imageDigest": "",
            "detail": "模型资产或计算配置尚未就绪",
        }


def require_binding(task):
    profile, state = binding(task.version.manifest, task.project_tag_id)
    if state["imageDigest"] != task.version.runtime_digest:
        raise ComputeError("模型环境或资产已变化，请重新试运行并发布版本", 409)
    return profile, state


@contextmanager
def lease(profile):
    import fcntl

    directory = app_path("cache", "model-runtime")
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "cpu.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ComputeError("模型计算正在使用，请稍后继续", 503) from error
        yield ""
