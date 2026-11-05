"""Preview decoding is incremental, bounded, and separate from final validation."""

import json

import pytest

from apps.agent.answer_preview import AnswerPreviewParser


def render(chunks, **options):
    parser = AnswerPreviewParser(**options)
    parts = []
    for chunk in chunks:
        change = parser.feed(chunk)
        if change.reset:
            parts.clear()
        parts.append(change.text)
    return "".join(parts), parser


@pytest.mark.parametrize(
    "raw",
    [
        '{"action":"final","answer":"中文与遥感🛰️"}',
        r'{"action":"final","answer":"引号\"、反斜线\\、换行\n、\u4e2d\u6587、\ud83d\ude80"}',
        '{"answer":"先生成正文","action":"final"}',
        ' \n```json\n{"action":"final","answer":"有代码围栏"}\n``` ',
        r'{"\u0061ction":"final","\u0061nswer":"转义键名"}',
    ],
)
def test_every_fragment_boundary_decodes_the_same_answer(raw):
    body = raw.strip().removeprefix("```json").removesuffix("```").strip()
    expected = json.loads(body)["answer"]
    for cut in range(len(raw) + 1):
        text, parser = render([raw[:cut], raw[cut:]])
        assert text == expected
        assert parser.complete and not parser.invalid
    text, parser = render(list(raw))
    assert text == expected and not parser.invalid


def test_answer_before_action_stays_hidden_until_final_value_is_closed():
    parser = AnswerPreviewParser()
    assert parser.feed('{"answer":"暂存正文",').text == ""
    assert parser.feed('"action":"fina').text == ""
    assert parser.feed('l"').text == "暂存正文"
    assert parser.feed("}").text == ""
    assert parser.complete


@pytest.mark.parametrize(
    "raw",
    [
        '{"action":"search_resources","arguments":{"answer":"工具参数不能显示"}}',
        '{"arguments":{"action":"final","answer":"嵌套不能显示"},"action":"search_resources"}',
        '{"action":"final","answer":{"answer":"嵌套回答不能显示"}}',
        '{"answer":"不可提前显示","action":"search_resources"}',
        '前言 {"action":"final","answer":"不从任意正文抽JSON"}',
        '```python\n{"action":"final","answer":"错误围栏"}\n```',
    ],
)
def test_tools_nested_values_and_non_json_prefixes_never_become_agent_preview(raw):
    text, parser = render(list(raw))
    assert text == "" and parser.invalid


@pytest.mark.parametrize(
    "suffix",
    [
        ',"action":"search_resources"}',
        ',"answer":"第二个值"}',
        ',"arguments":{"answer":"工具参数"}}',
        ',"other":1}',
        ",}",
    ],
)
def test_duplicate_or_extra_fields_reset_already_emitted_text(suffix):
    parser = AnswerPreviewParser()
    assert parser.feed('{"action":"final","answer":"先到的文本"').text == "先到的文本"
    change = parser.feed(suffix)
    assert change.reset and change.text == ""
    assert parser.invalid


@pytest.mark.parametrize("invalid", [r"\q", r"\u12xz", r"\ud800X", r"\udfff", "\n"])
def test_invalid_escapes_or_unicode_reset_unverified_preview(invalid):
    parser = AnswerPreviewParser()
    assert parser.feed('{"action":"final","answer":"有效前缀').text == "有效前缀"
    change = parser.feed(invalid)
    assert change.reset and parser.invalid


def test_split_unicode_escape_does_not_emit_partial_codepoint():
    parser = AnswerPreviewParser()
    assert parser.feed('{"action":"final","answer":"\\ud83').text == ""
    assert parser.feed("d\\u").text == ""
    assert parser.feed("de").text == ""
    assert parser.feed('80"}').text == "🚀"


def test_large_character_chunks_are_consumed_incrementally_with_a_fixed_cap():
    parser = AnswerPreviewParser(limit=32)
    chunks = ['{"answer":"', *("遥" for _ in range(20000)), '","action":"final"}']
    changes = [parser.feed(chunk) for chunk in chunks]
    assert "".join(change.text for change in changes) == "遥" * 32
    assert not any(change.text for change in changes[:-1])
    assert parser.complete and not parser.invalid
    assert parser._answer_length == 32
    assert not parser._answer_buffer


@pytest.mark.parametrize(
    "text",
    [
        "普通中文回答逐步到达",
        " \n带空格的回答",
        "`inline code` 与正文",
        "[列表]和中文🛰️",
    ],
)
def test_plain_text_is_incremental_only_for_chat(text):
    chat, parser = render(list(text), allow_plain=True)
    agent, _ = render(list(text))
    assert chat == text and not parser.invalid
    assert agent == ""


def test_chat_json_still_waits_for_confirmed_final_and_hides_tool_json():
    parser = AnswerPreviewParser(allow_plain=True)
    assert parser.feed('{"answer":"先别显示",').text == ""
    assert parser.feed('"action":"search_resources"}').reset
    assert (
        render(list('{"action":"final","answer":"正确正文"}'), allow_plain=True)[0]
        == "正确正文"
    )
