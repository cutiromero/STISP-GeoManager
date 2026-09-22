import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.agent.models import AgentPolicy
from apps.agent.policy import default_policy
from apps.agent.tools import execute, evidence_items
from apps.projects.context import project_scope

from tests.integration.test_agent import new_run, setup_agent  # noqa: F401


@pytest.mark.django_db
def test_system_info_is_policy_gated_and_evidence_is_reauthorizable(
    setup_agent, monkeypatch  # noqa: F811
):
    env = setup_agent
    policy = default_policy()
    policy["systemInfoEnabled"] = True
    AgentPolicy.objects.update_or_create(pk=1, defaults={"value": policy})
    monkeypatch.setattr(
        "apps.agent.tools._system_info",
        lambda user, value: {"platform": {"name": "test"}},
    )
    with project_scope(env["scope"]):
        run = new_run(env)
        result, pairs = execute(run, "get_system_info", {"sections": ["platform"]})
        assert result["platform"]["name"] == "test"
        run.evidence = evidence_items(run, "get_system_info", pairs)
        run.save(update_fields=["evidence"])
        # A non-resource evidence item survives the next authorization check.
        assert execute(run, "search_resources", {"query": ""})[0]["items"]


@pytest.mark.django_db
def test_internet_is_disabled_until_policy_switch(setup_agent):  # noqa: F811
    env = setup_agent
    with project_scope(env["scope"]):
        with pytest.raises(PermissionDenied):
            execute(
                new_run(env),
                "search_web",
                {"url": "https://example.com", "maxResults": 1},
            )


@pytest.mark.django_db
def test_internet_rejects_local_addresses(setup_agent):  # noqa: F811
    env = setup_agent
    policy = default_policy()
    policy["internetEnabled"] = True
    AgentPolicy.objects.update_or_create(pk=1, defaults={"value": policy})
    with project_scope(env["scope"]):
        run = new_run(env)
        run.internet_enabled = True
        run.save(update_fields=["internet_enabled"])
        with pytest.raises(ValidationError):
            execute(
                run,
                "search_web",
                {"url": "http://127.0.0.1:8000/secret", "maxResults": 1},
            )
