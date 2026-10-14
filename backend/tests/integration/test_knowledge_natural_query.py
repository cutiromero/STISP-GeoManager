"""Natural-language retrieval ranks actual concepts inside the authorized pool."""

# ruff: noqa: F811
import pytest

from apps.knowledge.models import KnowledgeEntry
from apps.knowledge.services import search_entries
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import Project, ProjectMembership
from tests.integration.test_knowledge import users  # noqa: F401

QUERY = (
    "检索青海东昆仑南坡（95,34,100,38）完整覆盖范围内部漏填检查规则，"
    "以及八宝山组（T3）的地层时代定义与适用条件。"
)


def entry(project, title, subject, aliases, **values):
    return KnowledgeEntry.objects.create(
        project_tag=project,
        title=title,
        subject=subject,
        aliases=aliases,
        statement="核对已有资料及适用条件。",
        category="检查知识",
        status=values.pop("status", "published"),
        domain=values.pop("domain", "geology"),
        **values,
    )


def relevant(project):
    return [
        entry(project, "完整制图范围内部漏填的条件化检查", "内部漏填", ["完整覆盖"]),
        entry(
            project, "八宝山组地层名称与时代属性一致性", "八宝山组", ["地层时代", "T3"]
        ),
    ]


def test_actual_long_query_promotes_concepts_over_low_id_coordinate_matches(users):
    _, _, reader, project = users
    with project_scope(ProjectScope((project.id,), project.id, reader.id)):
        for i in range(12):
            entry(project, f"旧资料{i}", f"无关对象{i}", ["100", "34"])
        expected = relevant(project)
        result = search_entries(reader, QUERY, domains=["geology"])
        assert [row["id"] for row in result["items"][:2]] == [
            expected[1].id,
            expected[0].id,
        ]
        assert len(result["items"]) == 8
        limited = search_entries(reader, QUERY, limit=1, domains=["geology"])
        assert limited["items"][0]["id"] == expected[1].id
        assert limited["total"] == result["total"]


def test_concept_matching_retains_projects_domains_public_reuse_and_drafts(users):
    _, _, reader, project = users
    other = Project.objects.create(name="其他项目", code="natural-query-other")
    public = Project.objects.get(pk=1)
    shared = entry(public, "公开漏填检查", "内部漏填", ["完整覆盖"])
    inaccessible = entry(other, "别的项目完整覆盖", "内部漏填", ["完整覆盖"])
    with project_scope(ProjectScope((project.id,), project.id, reader.id)):
        own = relevant(project)
        hidden = [
            inaccessible,
            entry(project, "未发布完整覆盖", "内部漏填", ["完整覆盖"], status="draft"),
            entry(
                project, "生态完整覆盖", "内部漏填", ["完整覆盖"], domain="arid_ecology"
            ),
        ]
        result = search_entries(reader, QUERY, domains=["geology"])
        ids = {row["id"] for row in result["items"]}
        assert ids == {shared.id, *(item.id for item in own)}
        assert not ids.intersection(item.id for item in hidden)
        ProjectMembership.objects.filter(project=project, user=reader).delete()
        from django.core.exceptions import PermissionDenied

        with pytest.raises(PermissionDenied):
            search_entries(reader, QUERY, domains=["geology"])


def test_alias_concept_match_is_case_insensitive_and_not_a_single_character(users):
    _, _, reader, project = users
    with project_scope(ProjectScope((project.id,), project.id, reader.id)):
        expected = entry(project, "植被指数", "vegetation index", ["NDVI"])
        unrelated = entry(project, "单字别名", "无关对象", ["查"])
        result = search_entries(reader, "请查看ndvi的适用条件", domains=["geology"])
        assert [row["id"] for row in result["items"]] == [expected.id]
        assert unrelated.id not in {row["id"] for row in result["items"]}
