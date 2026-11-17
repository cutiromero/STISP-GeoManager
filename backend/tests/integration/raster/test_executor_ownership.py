# ruff: noqa: F811
import json
import subprocess
import sys
import uuid

import pytest
from django.db import connection

from apps.raster.models import RasterProcessingJob
from apps.raster.services import executor_identity, jobs
from tests.integration.test_agent_runtime_heartbeat import wal_database  # noqa: F401


@pytest.mark.django_db(transaction=True)
@pytest.mark.efficiency
def test_live_other_process_job_is_not_a_restart_and_dead_owner_is_reconciled(
    wal_database, monkeypatch
):  # noqa:F811
    code = """import os,sys,json,time,django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','geomanager.test_settings')
from django.conf import settings
settings.DATABASES['default']['NAME']=sys.stdin.readline().strip()
django.setup()
from apps.raster.services.executor_identity import current_identity
print(json.dumps(current_identity()),flush=True)
time.sleep(30)
"""
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        process.stdin.write(str(connection.settings_dict["NAME"]) + "\n")
        process.stdin.flush()
        identity = json.loads(process.stdout.readline())
        assert executor_identity.alive(identity) is True
        record = RasterProcessingJob.objects.create(
            id=uuid.uuid4().hex,
            kind="export",
            status="running",
            executor_identity=identity,
            result={"inputRefs": []},
        )
        monkeypatch.setattr(jobs, "_JOBS", {})
        monkeypatch.setattr(jobs, "_RESTART_RECONCILED", False)
        assert jobs.get_job(record.pk).status == "running"
        record.refresh_from_db()
        assert record.status == "running"
        process.terminate()
        process.wait(timeout=5)
        assert executor_identity.alive(identity) is False
        jobs.reconcile_interrupted_jobs(job_ids=[record.pk])
        assert jobs.get_job(record.pk).status == "failed"
        record.refresh_from_db()
        assert record.status == "failed"
        assert "executor_identity" not in jobs.get_job(record.pk).as_dict()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


@pytest.mark.django_db
def test_executor_cannot_service_a_copied_candidate_database():
    identity = executor_identity.current_identity()
    assert executor_identity.alive(identity) is True
    assert (
        executor_identity.alive({**identity, "database": "different-database"}) is False
    )
    assert (
        executor_identity.alive({**identity, "instance": "old-process-incarnation"})
        is False
    )
