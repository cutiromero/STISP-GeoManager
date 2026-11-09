"""All tasks use shared read evidence; no cache can authorize access."""

# ruff: noqa: F811
import hashlib
from uuid import uuid4
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied

from apps.agent.tools import execute
from apps.catalog.models import DataResource
from apps.compute import result_reads
from apps.compute.data import preview
from apps.compute.packages import ComputeError
from apps.core.storage import app_path
from apps.projects.models import ProjectMembership
from tests.integration.test_agent_compute_loop import env, output, task, setup_compute  # noqa: F401

pytestmark = pytest.mark.efficiency


def result(e, text, key="summary"):
    e["body"] = {**e["body"], "idempotencyKey": uuid4().hex}
    t = task(e)
    o = output(t, key)
    path = app_path(
        "projects", str(t.project_tag_id), "compute", "outputs", str(t.id), key + ".csv"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    o.path = path.relative_to(app_path()).as_posix()
    o.size_bytes = path.stat().st_size
    o.checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    o.save()
    return o, path


@pytest.mark.parametrize(
    "text,fields",
    [
        ("a,b\n1,中文\n2,地质\n", ["a", "b"]),
        ("岩性,等级\n花岗岩,高\n片岩,低\n", ["岩性", "等级"]),
    ],
)
def test_agent_and_platform_preview_share_index_for_any_task(env, text, fields):
    o, path = result(env, text)
    with patch.object(
        result_reads, "_index_table", wraps=result_reads._index_table
    ) as build:
        first, _ = execute(
            env["run"],
            "read_compute_output",
            {"outputId": o.id, "offset": 0, "limit": 1},
        )
        second, _ = execute(
            env["run"],
            "read_compute_output",
            {"outputId": o.id, "offset": 1, "limit": 1},
        )
        shown = preview(o)
    assert first["columns"] == second["columns"] == shown["columns"] == fields
    assert first["total"] == second["total"] == 2
    assert first["nextOffset"] == 1 and second["nextOffset"] is None
    assert first["rows"][0] != second["rows"][0]
    assert build.call_count == 1
    assert hashlib.sha256(path.read_bytes()).hexdigest() == o.checksum


def test_new_task_new_data_never_reuses_previous_result_rows(env):
    first, _ = result(env, "a\nfirst\n", "first")
    second, _ = result(env, "different\nsecond\n", "second")
    for _ in range(2):
        a, _ = execute(env["run"], "read_compute_output", {"outputId": first.id})
        b, _ = execute(env["run"], "read_compute_output", {"outputId": second.id})
        assert a["rows"] == [{"a": "first"}]
        assert b["rows"] == [{"different": "second"}]
    assert first.task_id != second.task_id


@pytest.mark.parametrize(
    "change", ["membership", "resource_access", "expired", "cancelled", "file_content"]
)
def test_warm_evidence_does_not_bypass_live_boundaries(env, change):
    o, path = result(env, "a\nfirst\n")
    execute(env["run"], "read_compute_output", {"outputId": o.id})
    if change == "membership":
        ProjectMembership.objects.filter(
            project=env["project"], user=env["owner"]
        ).delete()
    elif change == "resource_access":
        DataResource.objects.filter(pk=env["resource"].pk).update(
            owner_only=True, maintainer=env["outsider"]
        )
    elif change == "expired":
        o.expired = True
        o.save(update_fields=["expired"])
    elif change == "cancelled":
        o.task.status = "cancelled"
        o.task.save(update_fields=["status"])
    else:
        path.write_text("a\nother\n")
    with pytest.raises((PermissionDenied, ComputeError)):
        execute(env["run"], "read_compute_output", {"outputId": o.id})
