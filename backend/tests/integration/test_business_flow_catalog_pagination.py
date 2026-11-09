"""All registered definitions stay discoverable with bounded metadata reads."""

from django.db import connection
from django.test.utils import CaptureQueriesContext
import pytest

from apps.business_flows.models import BusinessFlowDefinition
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent  # noqa: F401

# ruff: noqa: F811


@pytest.fixture
def catalog_rows(setup_agent):
    env = setup_agent
    with project_scope(env["scope"]):
        BusinessFlowDefinition.objects.bulk_create(
            [
                BusinessFlowDefinition(
                    project_tag_id=env["project"].pk,
                    owner=env["admin"],
                    code=f"flow-{index:02d}",
                    name=f"流程{index:02d}",
                    description="研究主题" if index == 50 else "普通科研路径",
                )
                for index in range(51)
            ]
        )
    return env


@pytest.mark.efficiency
def test_fifty_one_definitions_are_reachable_without_count(catalog_rows):
    env = catalog_rows
    with CaptureQueriesContext(connection) as queries:
        first = env["client"].get("/api/business-flows/", **env["header"])
    assert first.status_code == 200
    page = first.json()
    assert len(page["items"]) == 50 and page["nextOffset"] == 50
    assert not any("COUNT(" in row["sql"].upper() for row in queries)
    second = env["client"].get(
        "/api/business-flows/?offset=50&limit=50", **env["header"]
    )
    assert second.status_code == 200
    last = second.json()
    assert len(last["items"]) == 1 and "nextOffset" not in last
    assert len({row["id"] for row in page["items"] + last["items"]}) == 51


@pytest.mark.parametrize("query", ["流程50", "研究主题", "flow-50"])
def test_remote_search_reaches_a_definition_beyond_first_page(catalog_rows, query):
    env = catalog_rows
    response = env["client"].get("/api/business-flows/", {"q": query}, **env["header"])
    assert response.status_code == 200
    assert [row["code"] for row in response.json()["items"]] == ["flow-50"]
    assert "nextOffset" not in response.json()


@pytest.mark.parametrize(
    "parameters",
    [
        {"offset": "-1"},
        {"offset": "bad"},
        {"offset": "1000001"},
        {"limit": "0"},
        {"limit": "51"},
        {"limit": "1.5"},
    ],
)
def test_pagination_bounds_are_explicit(catalog_rows, parameters):
    env = catalog_rows
    assert (
        env["client"]
        .get("/api/business-flows/", parameters, **env["header"])
        .status_code
        == 400
    )


def test_query_pages_stay_in_the_current_project(catalog_rows):
    env = catalog_rows
    response = env["client"].get(
        "/api/business-flows/?q=flow-50&offset=0&limit=1", HTTP_X_PROJECT_ID="1"
    )
    assert response.status_code == 200 and response.json()["items"] == []
