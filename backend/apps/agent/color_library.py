from __future__ import annotations

import colorsys
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re


LIBRARY_PATH = Path(__file__).parent / "data" / "result_color_library.json"
MIN_DELTA_E = 12.0
MIN_WHITE_CONTRAST = 3.0
MIN_OUTLINE_CONTRAST = 1.25
OUTLINE_COLOR = "#202938"
MAX_CANDIDATES_PER_VALUE = 4


def rgb(color):
    return tuple(int(color[position : position + 2], 16) for position in (1, 3, 5))


@lru_cache(maxsize=16384)
def linear_rgb(color):
    return tuple(
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in (channel / 255 for channel in rgb(color))
    )


def luminance(color):
    return sum(
        weight * value
        for weight, value in zip(
            (0.2126, 0.7152, 0.0722), linear_rgb(color), strict=True
        )
    )


def contrast(first, second):
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


@lru_cache(maxsize=16384)
def lab(color):
    red, green, blue = linear_rgb(color)
    xyz = (
        (0.4124564 * red + 0.3575761 * green + 0.1804375 * blue) / 0.95047,
        0.2126729 * red + 0.7151522 * green + 0.0721750 * blue,
        (0.0193339 * red + 0.1191920 * green + 0.9503041 * blue) / 1.08883,
    )
    x_value, y_value, z_value = (
        value ** (1 / 3)
        if value > (6 / 29) ** 3
        else value / (3 * (6 / 29) ** 2) + 4 / 29
        for value in xyz
    )
    return (116 * y_value - 16, 500 * (x_value - y_value), 200 * (y_value - z_value))


def color_issues(color, used):
    if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        return ["invalid_color"]
    issues = []
    if contrast(color, "#ffffff") < MIN_WHITE_CONTRAST:
        issues.append("low_background_contrast")
    if contrast(color, OUTLINE_COLOR) < MIN_OUTLINE_CONTRAST:
        issues.append("low_outline_contrast")
    if color.casefold() in {other.casefold() for other in used}:
        issues.append("duplicate_color")
    elif any(math.dist(lab(color), lab(other)) < MIN_DELTA_E for other in used):
        issues.append("low_delta_e")
    return issues


def valid_color(color, used):
    return not color_issues(color, used)


@lru_cache(maxsize=1)
def palette():
    colors = []
    for hue in range(0, 360, 3):
        for lightness in (0.27, 0.36, 0.45, 0.54, 0.63):
            for saturation in (0.4, 0.65, 0.9):
                channels = colorsys.hls_to_rgb(hue / 360, lightness, saturation)
                color = "#" + "".join(
                    f"{round(channel * 255):02x}" for channel in channels
                )
                if valid_color(color, []):
                    colors.append(color)
    return tuple(dict.fromkeys(colors))


def fallback_color(name, used, reference=None):
    used = [color.lower() for color in used]
    colors = palette()
    seed = int(hashlib.sha256(name.encode()).hexdigest()[:8], 16) % len(colors)
    ordered = colors[seed:] + colors[:seed]
    if not reference:
        for color in ordered:
            if valid_color(color, used):
                return color
    available = (
        [color for color in ordered if valid_color(color, used)] if reference else []
    )
    if available:
        return (
            min(available, key=lambda color: math.dist(lab(color), lab(reference)))
            if reference
            else available[0]
        )
    remaining = [color for color in ordered if color not in used]
    if not remaining:
        for index in range(4096):
            color = "#" + hashlib.sha256(f"{name}:{index}".encode()).hexdigest()[:6]
            if color not in used and valid_color(color, []):
                return color
    return max(
        remaining,
        key=lambda color: min(
            (math.dist(lab(color), lab(other)) for other in used), default=100
        ),
    )


@lru_cache(maxsize=1)
def library():
    return json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))["entries"]


def normalize(value):
    return re.sub(r"[\s_\-]+", "", str(value)).casefold()


def candidates(field, values):
    domain = (
        "alteration"
        if field in {"alt", "mineral", "alteration"}
        else "grade"
        if field == "grade"
        else "lithology"
    )
    matches = []
    for value in values:
        needle = normalize(value)
        ranked = []
        for entry in library():
            terms = [normalize(term) for term in [entry["name"], *entry["aliases"]]]
            exact = needle in terms
            partial = any(len(term) >= 2 and term in needle for term in terms)
            if exact or partial:
                ranked.append(
                    (0 if exact else 1, entry["domain"] != domain, entry["id"], entry)
                )
        for rank, _, _, entry in sorted(ranked)[:MAX_CANDIDATES_PER_VALUE]:
            matches.append({"value": value, "relevance": rank, **entry})
    return sorted(
        matches, key=lambda item: (item["relevance"], item["value"], item["id"])
    )


def selected_entry(value, color, entries):
    return next(
        (
            entry
            for entry in entries
            if entry["value"] == value and entry["color"].casefold() == color.casefold()
        ),
        None,
    )
