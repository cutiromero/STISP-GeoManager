import json

import pytest
from django.contrib.auth.models import Permission

from apps.agent.models import AgentToolCall
from apps.agent.tool_contract_runtime import ToolContractError, argument_fingerprint
from apps.agent.tools import execute
from apps.projects.context import project_scope
from apps.projects.models import ProjectMembership
from tests.integration.test_agent import new_run, setup_agent  # noqa: F401

# ruff: noqa: F811
pytestmark = pytest.mark.django_db


def test_real_call_receipt_omits_argument_values_and_data(setup_agent):
    env = setup_agent
    with project_scope(env["scope"]):
        run = new_run(env)
        arguments = {"query": "人工样地"}
        result, _ = execute(run, "search_resources", arguments)
        assert result["items"]
    call = AgentToolCall._base_manager.get(run=run)
    assert call.status == "succeeded" and call.request_hash == argument_fingerprint(
        arguments
    )
    assert call.argument_keys == ["query"] and call.result_refs == {}
    response = env["client"].get(
        f"/api/agent/runs/{run.pk}/tool-calls/", **env["header"]
    )
    assert response.status_code == 200
    value = response.json()
    assert value["total"] == 1 and value["items"][0]["id"] == str(call.pk)
    assert "人工样地" not in response.content.decode()
    assert "never send this" not in response.content.decode()


def test_invalid_call_has_correlated_structured_receipt_before_reading_data(
    setup_agent,
):
    env = setup_agent
    with project_scope(env["scope"]):
        run = new_run(env)
        with pytest.raises(ToolContractError) as caught:
            execute(run, "search_resources", {"limit": True})
    call = AgentToolCall._base_manager.get(run=run)
    assert call.status == "failed" and call.error["requestId"] == str(call.pk)
    assert caught.value.tool_request_id == str(call.pk)
    assert call.error["fieldErrors"][0]["field"] == "$.limit"


def test_receipts_are_owner_project_and_live_permission_scoped(setup_agent):
    env = setup_agent
    with project_scope(env["scope"]):
        run = new_run(env)
        execute(run, "search_resources", {})
    url = f"/api/agent/runs/{run.pk}/tool-calls/"
    assert env["client"].get(url, HTTP_X_PROJECT_ID="1").status_code == 404
    ProjectMembership.objects.create(project=env["project"], user=env["other"])
    env["other"].user_permissions.add(*env["user"].user_permissions.all())
    env["client"].force_login(env["other"])
    assert env["client"].get(url, **env["header"]).status_code == 404
    env["client"].force_login(env["user"])
    env["user"].user_permissions.remove(
        *Permission.objects.filter(codename="use_data_agent")
    )
    assert env["client"].get(url, **env["header"]).status_code == 403


def test_failure_receipt_does_not_persist_exception_secret(setup_agent, monkeypatch):
    env = setup_agent

    def broken(*args):
        raise RuntimeError("SECRET-CONTENT /root/private/file")

    monkeypatch.setattr("apps.agent.tools._execute_authorized", broken)
    with project_scope(env["scope"]):
        run = new_run(env)
        with pytest.raises(RuntimeError):
            execute(run, "search_resources", {})
    call = AgentToolCall._base_manager.get(run=run)
    assert call.status == "failed" and "SECRET-CONTENT" not in json.dumps(call.error)
