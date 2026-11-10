import json
from statistics import median
from time import perf_counter

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.agent import resource_discovery
from apps.agent.models import AgentPolicy
from apps.agent.resource_search import description_excerpt
from apps.catalog.models import DataResource
from tests.integration.test_agent_resource_discovery import imported, workflow


CONFIGURATION = "搜索性能回归配置"
ORIGINAL_COUNT = 1000
FINAL_COUNT = 100
BENCHMARK_REPEATS = 5
MAX_SEARCH_QUERIES = 48
pytestmark = pytest.mark.django_db
pytest_plugins = ["tests.integration.test_agent_resource_discovery"]


@pytest.fixture
def search_env(env):
    env["project"].code = "02"
    env["project"].save(update_fields=["code"])
    from django.contrib.auth.models import Permission

    env["user"].user_permissions.add(
        *Permission.objects.filter(codename="add_dataresource")
    )
    policy, _ = AgentPolicy.objects.get_or_create(pk=1)
    policy.value = {**env["policy"], "operatorEnabled": True}
    policy.save()
    return env


def search(env, query="", **parameters):
    response = env["client"].get(
        "/api/agent/workflow-uploads/references/",
        {"q": query, **parameters},
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )
    assert response.status_code == 200, response.content
    return response.json()


def entry(env, name, description="", **values):
    return DataResource.objects.create(
        name=name,
        code="search-" + str(DataResource.objects.count()),
        data_type="table",
        description=description,
        project_tag_id=env["project"].id,
        **values,
    )


def test_search_excerpt_keeps_separated_hits_within_response_limit():
    description = "前言" * 500 + "233" + "背景" * 500 + "地质" + "附录" * 500
    excerpt = description_excerpt(description, ["233", "地质"])
    assert "233" in excerpt and "地质" in excerpt
    assert len(excerpt) <= 800


@pytest.mark.efficiency
def test_pending_import_does_not_hide_original_search_results(search_env):
    from apps.compute.models import ComputeImport

    env = search_env
    _, _, _, record = imported(env, name="尚未完成入库")
    ComputeImport.objects.filter(pk=record.pk).update(resource=None, status="queued")
    for url in ("/api/agent/resources/", "/api/agent/workflow-uploads/references/"):
        response = env["client"].get(url, {"q": env["resource"].name}, **env["header"])
        assert response.status_code == 200, response.content
        assert [item["id"] for item in response.json()["items"]] == [env["resource"].id]


@pytest.mark.efficiency
def test_empty_or_out_of_range_page_does_not_read_page_rows(search_env):
    for parameters in ({"q": "不存在关键词"}, {"page": 999}):
        with CaptureQueriesContext(connection) as captured:
            result = search(search_env, **parameters)
        assert result["items"] == []
        assert not any(
            '"catalog_dataresource"' in row["sql"] and "LIMIT 20" in row["sql"]
            for row in captured
        )


@pytest.mark.efficiency
def test_general_candidate_search_query_bound(search_env, monkeypatch):
    env = search_env
    DataResource.objects.bulk_create(
        [
            DataResource(
                name=f"查询上界资料 {index}",
                code=f"query-bound-{index}",
                data_type="table",
                project_tag_id=env["project"].id,
            )
            for index in range(60)
        ]
    )
    calls = []
    original = resource_discovery._discover_resources

    def discover(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(resource_discovery, "_discover_resources", discover)
    with CaptureQueriesContext(connection) as captured:
        response = env["client"].get(
            "/api/agent/resources/", {"q": "查询上界资料"}, **env["header"]
        )
    assert response.status_code == 200, response.content
    assert len(response.json()["items"]) == 50
    assert len(calls) == 1
    assert len(captured) <= MAX_SEARCH_QUERIES
    assert sum('"catalog_dataresource"' in row["sql"] for row in captured) <= 3


@pytest.mark.parametrize(
    "url", ["/api/agent/resources/", "/api/agent/workflow-uploads/references/"]
)
def test_numeric_search_ignores_machine_metadata(search_env, url):
    env = search_env
    descriptions = [
        "计算结果；任务 00000233-1111-4111-8111-111111111111；算法 构造交汇重建 1；SHA256 "
        + "a" * 64,
        "计算结果；任务 00000000-1111-4111-8111-111111111111；算法 执行获批修正 1；SHA256 "
        + "a" * 30
        + "233"
        + "a" * 31,
    ]
    hidden = [
        entry(env, name, description)
        for name, description in zip(
            [
                "构造交汇重建 几何与推测交汇点 11-06 13:48:00",
                "执行获批修正 修正后岩性图 11-04 12:34:56",
            ],
            descriptions,
        )
    ]
    technical = entry(
        env, "普通资料", source="source-233", storage_path="folder/233.csv"
    )
    DataResource.objects.filter(pk=technical.pk).update(code="internal-233")
    uploaded = entry(env, "上传资料", "MH-workflow任务资料，原文件：233.csv")
    named = entry(env, "233区域观测")
    described = entry(env, "地质观测", "该区域有233个有效采样点")
    old_matches = list(
        DataResource.objects.filter(description__icontains="233").values_list(
            "name", "description"
        )
    )
    print("\nNUMERIC_SEARCH_EQUIVALENT=" + json.dumps(old_matches, ensure_ascii=False))
    response = env["client"].get(url, {"q": "233"}, **env["header"])
    assert response.status_code == 200, response.content
    rows = response.json()["items"]
    assert [row["id"] for row in rows] == [named.id, described.id]
    assert not {item.id for item in [*hidden, uploaded]} & {row["id"] for row in rows}
    assert "233" in rows[1]["description"]


@pytest.mark.parametrize(
    "url", ["/api/agent/resources/", "/api/agent/workflow-uploads/references/"]
)
def test_search_intersects_terms_ranks_names_and_returns_distant_description_hits(
    search_env, url
):
    env = search_env
    older = entry(env, "地质数据旧")
    newer = entry(env, "地质数据新")
    mixed = entry(env, "地质观测", "前言" * 500 + "数据来自野外" + "附录" * 500)
    described = entry(env, "区域说明", "地质" + "背景" * 500 + "数据")
    entry(env, "只有地质")
    entry(env, "只有数据")
    response = env["client"].get(url, {"q": "  地质   数据  "}, **env["header"])
    assert response.status_code == 200, response.content
    rows = response.json()["items"]
    assert [row["id"] for row in rows] == [newer.id, older.id, mixed.id, described.id]
    assert "数据" in rows[2]["description"]
    assert "地质" in rows[3]["description"] and "数据" in rows[3]["description"]
    assert all(len(row["description"]) <= 800 for row in rows)
    empty = env["client"].get(url, {"q": "不存在关键词"}, **env["header"]).json()
    assert empty["items"] == []


@pytest.mark.efficiency
@pytest.mark.parametrize(
    "url", ["/api/agent/resources/", "/api/agent/workflow-uploads/references/"]
)
def test_search_rechecks_owner_only_project_and_membership(search_env, url):
    from apps.projects.models import Project, ProjectMembership

    env = search_env
    allowed = entry(env, "授权资料")
    hidden = entry(env, "授权隐私", owner_only=True, maintainer=env["other"])
    cross = entry(env, "授权跨项目")
    project = Project.objects.create(code="search-other", name="另一项目")
    DataResource._base_manager.filter(pk=cross.pk).update(project_tag_id=project.id)

    def read():
        return env["client"].get(url, {"q": "授权"}, **env["header"])

    assert [row["id"] for row in read().json()["items"]] == [allowed.id]
    allowed.owner_only, allowed.maintainer = True, env["other"]
    allowed.save(update_fields=["owner_only", "maintainer"])
    assert read().json()["items"] == []
    hidden.maintainer = env["user"]
    hidden.save(update_fields=["maintainer"])
    assert [row["id"] for row in read().json()["items"]] == [hidden.id]
    ProjectMembership.objects.filter(project=env["project"], user=env["user"]).delete()
    assert read().status_code == 404


@pytest.mark.efficiency
def test_catalog_search_measurements(search_env, monkeypatch):
    env = search_env
    DataResource.objects.bulk_create(
        [
            DataResource(
                name=f"区域资料 {index}",
                code=f"search-original-{index}",
                data_type="table",
                project_tag_id=env["project"].id,
                description="区域地质观测" * 100,
            )
            for index in range(ORIGINAL_COUNT)
        ]
    )
    for index in range(FINAL_COUNT):
        item, task, output, _ = imported(
            env, name=f"成果资料 {index}", key="intersections"
        )
        workflow(env, item, task, output, stage="relations")
    stages = {}
    current = {}
    from apps.agent import workflow_uploads

    monkeypatch.setattr(
        workflow_uploads,
        "catalog_profile",
        lambda *_: pytest.fail("候选搜索不应读取资料画像"),
    )
    for name in (
        "_discover_resources",
        "_internal_resource_ids",
        "_final_resource_ids",
        "_report_resource_ids",
    ):
        original = getattr(resource_discovery, name)

        def measured(*args, _original=original, _name=name, **kwargs):
            started = perf_counter()
            if _name == "_discover_resources":
                current["discovery_calls"] = current.get("discovery_calls", 0) + 1
            try:
                return _original(*args, **kwargs)
            finally:
                current[_name] = (
                    current.get(_name, 0) + (perf_counter() - started) * 1000
                )

        monkeypatch.setattr(resource_discovery, name, measured)
    for query in ("", "成果资料 77", "233"):
        records = []
        for _ in range(BENCHMARK_REPEATS):
            current = {}
            started = perf_counter()
            sql_times = {"count_sql_ms": 0, "page_sql_ms": 0, "directories_sql_ms": 0}

            def measure_sql(execute, sql, params, many, context):
                started = perf_counter()
                try:
                    return execute(sql, params, many, context)
                finally:
                    if '"catalog_dataresource"' in sql:
                        label = (
                            "count_sql_ms"
                            if sql.startswith("SELECT COUNT(")
                            else "page_sql_ms"
                            if "LIMIT 20" in sql
                            else "directories_sql_ms"
                            if sql.startswith("SELECT DISTINCT")
                            else None
                        )
                        if label:
                            sql_times[label] += (perf_counter() - started) * 1000

            with (
                CaptureQueriesContext(connection) as captured,
                connection.execute_wrapper(measure_sql),
            ):
                result = search(env, query)
            elapsed = (perf_counter() - started) * 1000
            record = {
                **current,
                **sql_times,
                "request_ms": elapsed,
                "queries": len(captured),
                "total": result["total"],
            }
            record["resource_queries"] = sum(
                '"catalog_dataresource"' in row["sql"] for row in captured
            )
            assert len(captured) <= MAX_SEARCH_QUERIES
            assert record["resource_queries"] <= 6
            assert record["discovery_calls"] == 1
            records.append(record)
        stages[query] = {
            key: round(median(record[key] for record in records), 3)
            for key in records[0]
        }
    print("\nCATALOG_SEARCH_MEASUREMENTS=" + json.dumps(stages, ensure_ascii=False))
    assert stages[""]["total"] == ORIGINAL_COUNT + FINAL_COUNT + 1
