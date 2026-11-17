import pytest
from django.contrib.auth.models import Permission

from apps.agent.capability_catalog import contracts
from apps.agent.models import AgentPolicy, AgentRun
from apps.agent.policy import default_policy
from apps.catalog.models import DataResource
from tests.integration.test_agent import setup_agent  # noqa: F401

# ruff: noqa: F811
pytestmark = pytest.mark.django_db
URL = "/api/agent/capabilities/"


def test_catalog_is_scoped_read_only_and_filtered(setup_agent):
    env = setup_agent
    before = (DataResource._base_manager.count(), AgentRun._base_manager.count())
    response = env["client"].get(URL, **env["header"])
    assert response.status_code == 200
    value = response.json()
    assert value["projectId"] == env["project"].pk
    names = {item["name"] for item in value["items"]}
    assert {"search_resources", "describe_resource", "read_rows"} <= names
    assert not names & {
        "search_web",
        "execute_operator",
        "import_compute_result",
        "prepare_map_workspace",
    }
    assert all(
        item["inputSchema"]["additionalProperties"] is False for item in value["items"]
    )
    assert (
        DataResource._base_manager.count(),
        AgentRun._base_manager.count(),
    ) == before
    assert env["resource"].storage_path not in response.content.decode()


def test_catalog_rechecks_features_and_policy(setup_agent):
    env = setup_agent
    env["user"].user_permissions.add(
        *Permission.objects.filter(
            codename__in=["add_workspacescene", "view_workspacescene", "submit_task"]
        )
    )
    policy = default_policy()
    policy["operatorEnabled"] = True
    AgentPolicy.objects.update_or_create(pk=1, defaults={"value": policy})
    names = {
        item["name"] for item in env["client"].get(URL, **env["header"]).json()["items"]
    }
    assert {"prepare_map_workspace", "execute_operator"} <= names
    policy["mapDisplayEnabled"] = False
    policy["operatorEnabled"] = False
    AgentPolicy.objects.filter(pk=1).update(value=policy)
    names = {
        item["name"] for item in env["client"].get(URL, **env["header"]).json()["items"]
    }
    assert not names & {"prepare_map_workspace", "execute_operator"}


def test_catalog_denies_missing_project_login_and_revoked_access(setup_agent):
    env = setup_agent
    assert env["client"].get(URL).status_code == 400
    env["client"].logout()
    assert env["client"].get(URL).status_code == 401
    env["client"].force_login(env["other"])
    assert env["client"].get(URL, **env["header"]).status_code in {403, 404}


def test_every_registered_tool_has_generated_contract():
    from apps.agent.tools import TOOLS

    assert set(contracts()) == set(TOOLS)
    for name, value in contracts().items():
        assert set(value["inputSchema"].get("properties", {})) == set(
            TOOLS[name].arguments
        )
