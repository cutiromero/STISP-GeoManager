"""Linear, conservative decoding of an unverified final-answer JSON string."""

from __future__ import annotations

from dataclasses import dataclass


# Configuration: previews are bounded independently of the final answer.
MAX_PREVIEW_CHARACTERS = 24000
PREVIEW_EVENT_KIND = "answer_preview"
JSON_WHITESPACE = " \t\r\n"
ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


def stored_answer_preview(run):
    """Use the latest small snapshot without reading or rewriting model context."""
    if run.status == "succeeded":
        return ""
    text = (
        run.events.filter(kind=PREVIEW_EVENT_KIND)
        .order_by("-id")
        .values_list("text", flat=True)
        .first()
    )
    return text[:MAX_PREVIEW_CHARACTERS] if isinstance(text, str) else ""


@dataclass(frozen=True)
class PreviewDelta:
    text: str = ""
    reset: bool = False


class AnswerPreviewParser:
    """Read each input character once; never render tool names or arguments.

    Only an object containing action/answer string fields is eligible. Answer
    text preceding action is buffered until the exact action value is final.
    Any later structural ambiguity invalidates the entire tentative preview.
    The worker remains responsible for strict final protocol validation.
    """

    def __init__(self, limit: int = MAX_PREVIEW_CHARACTERS, *, allow_plain=False):
        self.limit = limit
        self.allow_plain = allow_plain
        self.invalid = False
        self.complete = False
        self._state = "leading"
        self._fenced = False
        self._ticks = 0
        self._language = ""
        self._seen: set[str] = set()
        self._key = ""
        self._string_kind = ""
        self._string: list[str] = []
        self._escaped = False
        self._unicode: str | None = None
        self._high_surrogate: int | None = None
        self._action_final = False
        self._answer_buffer: list[str] = []
        self._answer_length = 0
        self._delta: list[str] = []
        self._leading_space: list[str] = []

    def feed(self, chunk: str) -> PreviewDelta:
        if self.invalid:
            return PreviewDelta()
        self._delta = []
        for character in chunk:
            self._consume(character)
            if self.invalid:
                self.complete = False
                self._answer_buffer.clear()
                return PreviewDelta(reset=True)
        return PreviewDelta(text="".join(self._delta))

    def _plain(self, text: str):
        for character in text:
            if 0xD800 <= ord(character) <= 0xDFFF:
                self.invalid = True
                return
            if self._answer_length < self.limit:
                self._answer_length += 1
                self._delta.append(character)

    def _begin_plain(self, character: str):
        self._state = "plain"
        self._plain("".join(self._leading_space) + "`" * self._ticks + character)
        self._leading_space.clear()

    def _begin_string(self, kind: str):
        self._state = "string"
        self._string_kind = kind
        self._string = []
        self._escaped = False
        self._unicode = None
        self._high_surrogate = None

    def _decoded(self, character: str):
        number = ord(character)
        if self._high_surrogate is not None:
            if not 0xDC00 <= number <= 0xDFFF:
                self.invalid = True
                return
            character = chr(
                0x10000 + ((self._high_surrogate - 0xD800) << 10) + number - 0xDC00
            )
            self._high_surrogate = None
        elif 0xD800 <= number <= 0xDBFF:
            self._high_surrogate = number
            return
        elif 0xDC00 <= number <= 0xDFFF:
            self.invalid = True
            return
        if self._string_kind == "answer":
            if self._answer_length < self.limit:
                self._answer_length += 1
                target = self._delta if self._action_final else self._answer_buffer
                target.append(character)
        else:
            self._string.append(character)
            if len(self._string) > 6:
                self.invalid = True

    def _end_string(self):
        if self._high_surrogate is not None:
            self.invalid = True
            return
        value = "".join(self._string)
        if self._string_kind == "key":
            if value not in {"action", "answer"} or value in self._seen:
                self.invalid = True
                return
            self._seen.add(value)
            self._key = value
            self._state = "colon"
            return
        if self._string_kind == "action":
            if value != "final":
                self.invalid = True
                return
            self._action_final = True
            self._delta.extend(self._answer_buffer)
            self._answer_buffer.clear()
        self._state = "comma"

    def _consume_string(self, character: str):
        if self._unicode is not None:
            if character not in "0123456789abcdefABCDEF":
                self.invalid = True
                return
            self._unicode += character
            if len(self._unicode) == 4:
                self._decoded(chr(int(self._unicode, 16)))
                self._unicode = None
            return
        if self._escaped:
            self._escaped = False
            if character == "u":
                self._unicode = ""
            elif character in ESCAPES:
                self._decoded(ESCAPES[character])
            else:
                self.invalid = True
        elif character == "\\":
            self._escaped = True
        elif character == '"':
            self._end_string()
        elif ord(character) < 0x20:
            self.invalid = True
        else:
            self._decoded(character)

    def _consume(self, character: str):
        if self._state == "plain":
            self._plain(character)
            return
        if self._state == "string":
            self._consume_string(character)
            return
        if self._state == "leading":
            if character in JSON_WHITESPACE:
                if len(self._leading_space) < self.limit:
                    self._leading_space.append(character)
                return
            if character == "`":
                self._fenced, self._ticks, self._state = True, 1, "ticks"
            elif character == "{":
                self._state = "key"
            elif self.allow_plain:
                self._begin_plain(character)
            else:
                self.invalid = True
            return
        if self._state == "ticks":
            if character != "`":
                if self.allow_plain:
                    self._begin_plain(character)
                else:
                    self.invalid = True
            else:
                self._ticks += 1
                if self._ticks == 3:
                    self._state = "language"
            return
        if self._state == "language":
            if character in JSON_WHITESPACE or character == "{":
                if self._language not in {"", "json"}:
                    self.invalid = True
                else:
                    self._state = "key" if character == "{" else "object"
            else:
                self._language += character.lower()
                if not "json".startswith(self._language):
                    self.invalid = True
            return
        if self._state == "object":
            if character in JSON_WHITESPACE:
                return
            if character == "{":
                self._state = "key"
            else:
                self.invalid = True
            return
        if self._state == "done":
            if character in JSON_WHITESPACE:
                return
            if self._fenced and character == "`":
                self._ticks, self._state = 1, "closing_ticks"
            else:
                self.invalid = True
            return
        if self._state == "closing_ticks":
            if character != "`":
                self.invalid = True
            else:
                self._ticks += 1
                if self._ticks == 3:
                    self._state = "tail"
            return
        if self._state == "tail":
            self.invalid = character not in JSON_WHITESPACE
            return
        if character in JSON_WHITESPACE:
            return
        if self._state == "key" and character == '"':
            self._begin_string("key")
        elif self._state == "colon" and character == ":":
            self._state = "value"
        elif self._state == "value" and character == '"':
            self._begin_string(self._key)
        elif self._state == "comma" and character == ",":
            self._state = "key"
        elif (
            self._state == "comma"
            and character == "}"
            and self._seen == {"action", "answer"}
        ):
            self.complete = True
            self._state = "done"
        else:
            self.invalid = True
