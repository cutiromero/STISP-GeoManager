from __future__ import annotations

from django.utils.translation import get_language


def is_english() -> bool:
    return (get_language() or "").lower().startswith("en")


def localized(chinese: str, english: str) -> str:
    return english if is_english() else chinese
