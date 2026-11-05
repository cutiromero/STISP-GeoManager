from io import StringIO

from django.core.management import call_command

from apps.agent.conversation_titles import DEFAULT_LOGIC_PROMPT, update_logic_title
from apps.agent.models import AgentRun, Conversation
from apps.projects.context import project_scope
from tests.integration.test_agent import setup_agent as setup_agent


def test_logic_titles_use_material_time_and_id_without_changing_custom_titles(
    setup_agent,
):
    env = setup_agent
    env["project"].code = "02"
    env["project"].save(update_fields=["code"])
    env["resource"].name = "海德乌拉岩性图"
    env["resource"].save(update_fields=["name"])
    with project_scope(env["scope"]):
        conversation = env["conversation"]
        conversation.title = DEFAULT_LOGIC_PROMPT
        conversation.save(update_fields=["title"])
        run = AgentRun.objects.create(
            owner=env["user"],
            conversation=conversation,
            model="mock",
            prompt=DEFAULT_LOGIC_PROMPT,
            resource_ids=[env["resource"].id],
            idempotency_key="title-first",
        )
        assert update_logic_title(run)
        assert "海德乌拉岩性图 岩性·构造·蚀变检查" in conversation.title
        assert f"#{run.id}" in conversation.title
        custom = conversation.title
        assert not update_logic_title(run)
        assert conversation.title == custom
        conversation.title = "我的自定义地质分析"
        conversation.save(update_fields=["title"])
        assert not update_logic_title(run)


def test_backfill_only_default_titles_in_logic_projects_is_idempotent(setup_agent):
    env = setup_agent
    env["project"].code = "02"
    env["project"].save(update_fields=["code"])
    with project_scope(env["scope"]):
        conversation = env["conversation"]
        conversation.title = DEFAULT_LOGIC_PROMPT + " 继续检查"
        conversation.save(update_fields=["title"])
        AgentRun.objects.create(
            owner=env["user"],
            conversation=conversation,
            model="mock",
            prompt=DEFAULT_LOGIC_PROMPT,
            resource_ids=[env["resource"].id],
            idempotency_key="title-backfill",
        )
    output = StringIO()
    call_command("backfill_logic_titles", stdout=output)
    conversation.refresh_from_db()
    assert conversation.title.startswith(DEFAULT_LOGIC_PROMPT)
    assert "待回填 1" in output.getvalue()
    call_command("backfill_logic_titles", apply=True, stdout=StringIO())
    conversation.refresh_from_db()
    assert not conversation.title.startswith(DEFAULT_LOGIC_PROMPT)
    output = StringIO()
    call_command("backfill_logic_titles", apply=True, stdout=output)
    assert "已回填 0" in output.getvalue()
    assert Conversation.objects.count() >= 1


def test_other_project_titles_are_untouched(setup_agent):
    env = setup_agent
    with project_scope(env["scope"]):
        run = AgentRun.objects.create(
            owner=env["user"],
            conversation=env["conversation"],
            model="mock",
            prompt=DEFAULT_LOGIC_PROMPT,
            idempotency_key="title-other",
        )
        assert not update_logic_title(run)
        assert run.conversation.title == "新会话"
