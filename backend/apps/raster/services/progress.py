from __future__ import annotations

import re


def normalize_progress_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\r", " ").strip())


def parse_progress_percent(text: str) -> int | None:
    percent_matches = re.findall(r"(?<!\d)(\d{1,3})(?:\.\d+)?\s*%", text)
    for raw in reversed(percent_matches):
        value = int(raw)
        if 0 <= value <= 100:
            return value
    progress_marks = re.findall(r"(?<!\d)(\d{1,3})(?:\.\.+|\.+)", text)
    for raw in reversed(progress_marks):
        value = int(raw)
        if 0 <= value <= 100:
            return value
    if "done" in text.lower():
        return 100
    return None
