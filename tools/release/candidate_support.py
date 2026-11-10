"""候选元数据隔离；不包含账号、业务夹具或浏览器认证资料。"""

from pathlib import Path
import json
import os
import sys
import tempfile
import tomllib

OPS = CANDIDATE = CODE = CONFIG = STATE = ISOLATION = None


def configure(operations):
    global OPS, CANDIDATE, CODE, CONFIG, STATE, ISOLATION
    OPS = Path(operations)
    CANDIDATE = OPS / "candidate"
    CODE = CANDIDATE / "code"
    CONFIG = CANDIDATE / "app.toml"
    STATE = OPS / "acceptance-state.json"
    ISOLATION = OPS / "candidate-isolation.json"


def write(path, value):
    path = Path(path)
    assert path.resolve().is_relative_to(OPS)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, encoding="utf-8"
    ) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, indent=2)
    temporary.chmod(0o600)
    temporary.replace(path)


def read(path):
    return json.loads(Path(path).read_text())


def bootstrap():
    # Check TOML before Django AppConfig can create files or run startup hooks.
    assert CONFIG.is_file(), "Root must prepare candidate/app.toml first"
    raw = tomllib.loads(CONFIG.read_text())
    storage = raw["application"]["storage"]
    for name in ("app_data", "research_data_root"):
        assert Path(storage[name]).resolve().is_relative_to(CANDIDATE.resolve()), name
    assert raw["runtime"].get("disable_catalog_startup_scan") is True
    assert raw["runtime"].get("disable_raster_startup_scan") is True
    assert (CODE / ".runtime/config-path").read_text().strip() == str(CONFIG)
    os.chdir(CODE / "backend")
    sys.path.insert(0, str(CODE / "backend"))
    os.environ["DJANGO_SETTINGS_MODULE"] = "geomanager.settings"
    import django

    django.setup()
    from django.conf import settings

    assert settings.PROGRAM_ROOT.resolve() == CODE.resolve()
    assert settings.PROJECT_CONFIG.config_path.resolve() == CONFIG.resolve()
    return settings


def database_identity():
    from django.conf import settings

    path = Path(settings.DATABASES["default"]["NAME"]).resolve()
    assert path.is_relative_to(CANDIDATE.resolve())
    value = path.stat()
    return {"path": str(path), "device": value.st_dev, "inode": value.st_ino}


def isolate():
    """Run after copying/migrating metadata and before starting any worker."""
    if ISOLATION.exists():
        saved = read(ISOLATION)
        assert saved["database"] == database_identity(), (
            "Candidate database was replaced"
        )
        return saved
    assert not STATE.exists(), "Never quarantine an already initialized QA run"
    from django.db import transaction
    from django.utils import timezone
    from django.contrib.sessions.models import Session
    from apps.agent.models import (
        AgentRun,
        AgentWorkflow,
        AgentComputeFollowup,
        AgentRuntime,
    )
    from apps.compute.models import (
        ComputeTask,
        ComputeImport,
        ComputeAttempt,
        ComputeOutput,
        RuntimeLease,
    )
    from apps.raster.models import RasterProcessingJob

    now = timezone.now()
    marker = "候选环境：复制历史已隔离，禁止执行或恢复"
    with transaction.atomic():
        counts = {
            "agentRuns": AgentRun._base_manager.all().update(
                status="interrupted",
                cancel_requested=True,
                detail=marker,
                execution_state={},
            ),
            "workflows": AgentWorkflow._base_manager.all().update(
                status="interrupted",
                cancel_requested=True,
                pause_requested=False,
                paused_from="",
                detail=marker,
                heartbeat=None,
            ),
            "followups": AgentComputeFollowup.objects.all().update(
                status="blocked", auto_import=False, detail=marker
            ),
            "computeTasks": ComputeTask._base_manager.all().update(
                status="interrupted", stage=marker, attempt_token="", heartbeat=None
            ),
            "computeImports": ComputeImport.objects.all().update(
                status="failed", error=marker, heartbeat=None
            ),
            "computeAttempts": ComputeAttempt.objects.all().update(
                status="interrupted", finished_at=now
            ),
            "oldOutputsExpired": ComputeOutput.objects.all().update(expired=True),
            "rasterJobs": RasterProcessingJob._base_manager.filter(
                status__in=["queued", "running"]
            ).update(status="failed", stage="quarantined", error=marker),
            "agentLeases": AgentRuntime.objects.all().update(heartbeat=None, detail={}),
            "computeLeases": RuntimeLease.objects.all().update(
                heartbeat=None, detail={}, token=""
            ),
            "copiedSessionsRemoved": Session.objects.all().delete()[0],
        }
    value = {
        "isolated": True,
        "database": database_identity(),
        "counts": counts,
        "at": now.isoformat(),
        "productionDataModified": False,
    }
    write(ISOLATION, value)
    return value


def require_isolated():
    assert ISOLATION.is_file(), "Run isolate before workers or QA initialization"
    assert read(ISOLATION)["database"] == database_identity()
