"""Keep live evidence authorization independent of catalog/result size."""

# ruff: noqa: F811
import gzip
import json
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.agent import resource_discovery
from apps.agent.policy import default_policy
from apps.agent.resource_discovery import discovery_scope, discover_resources
from apps.agent.selections import check_context_sources
from apps.agent.tools import check_evidence
from apps.catalog.models import DataResource
from apps.projects.context import project_scope
from tests.integration.test_agent import new_run, setup_agent  # noqa: F401

pytestmark = pytest.mark.efficiency


@pytest.fixture
def batch(setup_agent):
    env = setup_agent
    with project_scope(env["scope"]):
        resources = DataResource.objects.bulk_create(
            [
                DataResource(
                    name=f"资料{i}",
                    code=f"batch-{i}",
                    data_type="table",
                    project_tag_id=env["project"].id,
                )
                for i in range(50)
            ]
        )
        run = new_run(env)
        run.evidence = [
            {
                "id": i + 1,
                "tool": "search_resources",
                "resourceId": resource.id,
                "result": {"id": resource.id, "name": resource.name},
            }
            for i, resource in enumerate(resources)
        ]
        run.save(update_fields=["evidence"])
    return env, run, resources


def test_fifty_sources_share_one_provenance_plan_and_remain_live(batch):
    env, run, resources = batch
    with project_scope(env["scope"]), discovery_scope():
        with patch.object(
            resource_discovery,
            "_final_resource_ids",
            wraps=resource_discovery._final_resource_ids,
        ) as build:
            check_context_sources(run, env["user"], default_policy())
        assert build.call_count == 1
        # Even in the same check scope we cache the query plan, never ACL rows.
        list(discover_resources(env["user"], default_policy()))
        DataResource.objects.filter(pk=resources[0].id).update(
            owner_only=True, maintainer=env["other"]
        )
        with pytest.raises(PermissionDenied):
            check_evidence(run, env["user"], default_policy())
    # A fresh poll cannot inherit provenance decisions from the previous one.
    with project_scope(env["scope"]), discovery_scope():
        with pytest.raises(PermissionDenied):
            check_context_sources(run, env["user"], default_policy())


def test_gzipped_poll_preserves_all_evidence_and_events(batch):
    env, run, resources = batch
    response = env["client"].get(
        f"/api/agent/runs/{run.id}/", HTTP_ACCEPT_ENCODING="gzip", **env["header"]
    )
    assert response.status_code == 200
    assert response["Content-Encoding"] == "gzip"
    payload = json.loads(gzip.decompress(response.content))
    assert payload["run"]["id"] == run.id and len(payload["run"]["evidence"]) == 50


def test_authorization_query_count_does_not_grow_per_resource(batch):
    env, run, resources = batch
    original = list(run.evidence)
    with project_scope(env["scope"]):
        run.evidence = original[:1]
        with CaptureQueriesContext(connection) as small, discovery_scope():
            check_context_sources(run, env["user"], default_policy())
        run.evidence = original
        with CaptureQueriesContext(connection) as many, discovery_scope():
            check_context_sources(run, env["user"], default_policy())
        assert len(many) <= len(small) + 3
