"""Expert-facing lithology names/symbols, separate from frozen calculation IDs."""

import re


UNIT_ID = re.compile(r"(?<![A-Za-z0-9_-])U[0-9]{3,}(?![A-Za-z0-9_-])")
FEATURE_ID = re.compile(
    r"(?<![A-Za-z0-9_])(?:F[0-9]{4,}|AR-[0-9]+|A-U[0-9]{3,})(?![A-Za-z0-9_])"
)
NO_SYMBOL = "地质符号未登记"


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def unit_table(plan):
    value = (plan.get("unitOverrides") or {}).get("units", {})
    return value if isinstance(value, dict) else {}


def unit_label(code, units, properties=None):
    code = _text(code)
    properties = properties or {}
    saved = units.get(code)
    entry = saved if isinstance(saved, dict) else {}
    symbol = _text(properties.get("display_symbol")) or _text(
        entry.get("display_symbol")
    )
    name = _text(properties.get("name")) or _text(entry.get("name"))
    # On ordinary vector inputs, geo_sym is the confirmed map-symbol field.
    # Archive inputs give the display symbol in a separate field; U… is a key.
    if (
        not symbol
        and code
        and not UNIT_ID.fullmatch(code)
        and not FEATURE_ID.fullmatch(code)
    ):
        symbol = code if code != name else ""
    if symbol and name and symbol != name:
        return f"{symbol}（{name}）"
    return symbol or name or NO_SYMBOL


def unit_targets(value, units):
    value = _text(value)
    if not value:
        return ""
    codes = [value] if value in units else [part.strip() for part in value.split(" / ")]
    return "、".join(dict.fromkeys(unit_label(code, units) for code in codes))


def expert_text(value, units):
    """Replace display-only references; no inputs or signed edits are rewritten."""
    if not isinstance(value, str):
        return value
    value = FEATURE_ID.sub("图斑", value)
    return UNIT_ID.sub(lambda match: unit_label(match.group(), units), value)


def object_code(item, properties):
    observed = item.get("observations", {}) or {}
    if code := _text(properties.get("geo_sym")) or _text(observed.get("observed_code")):
        return code
    # Older L-01/L-02 issue rows start with the measured source code before
    # 图斑. Do not infer it from a host code or a later mention in model prose.
    match = re.match(r"^(U[0-9]{3,})(?=图斑)", _text(item.get("title")))
    return match.group(1) if match else ""


def decorate_lithology(
    item, units, properties=None, *, current_code="", target_code=""
):
    if item.get("element") != "lithology":
        return item
    properties = properties or {}
    observed = item.get("observations", {}) or {}
    code = current_code or object_code(item, properties)
    action = _text(item.get("action"))
    state = _text(item.get("suggestedState"))
    candidate = target_code or _text(item.get("candidateTargetCode"))
    if not candidate and action in {"reclassify", "set_code", "merge"}:
        candidate = (
            state.removeprefix(action + " ") if state.startswith(action + " ") else ""
        )
    current = unit_label(code, units, properties)
    target = unit_targets(candidate, units)
    # Only send the codes actually used on this issue, not the full vocabulary
    # repeated for each item on a paginated detail read.
    visible_codes = {code, *candidate.split(" / ")}
    for key in ("observed_code", "expected_code", "host_code", "dominant_code"):
        value = _text(observed.get(key))
        if value:
            visible_codes.add(value)
    existing_targets = observed.get("archive_local_targets")
    if isinstance(existing_targets, list):
        for target_row in existing_targets:
            if isinstance(target_row, dict):
                visible_codes.add(_text(target_row.get("code")))
    code_labels = {key: unit_label(key, units) for key in sorted(visible_codes) if key}
    if code:
        code_labels[code] = current
    display = {"current": current, "target": target, "codes": code_labels}
    return {
        **item,
        "title": expert_text(item.get("title"), units),
        "reason": expert_text(item.get("reason"), units),
        "currentState": current,
        "observations": {**observed, "lithology_display": display},
    }


def read_bound_lithology(workflow, user, policy, feature_ids):
    """One attribute-only query for the already-authorized page's original features."""
    from django.core.exceptions import PermissionDenied
    from apps.catalog.vector_store import DataQueryError, feature_display_attributes
    from .workflow_resources import resolve_workflow_resource

    if not feature_ids:
        return {}
    plan = workflow.plan
    bound = (plan.get("workingCopies") or {}).get("lithology") or (
        plan.get("inputs") or {}
    ).get("lithology")
    if type(bound) is not int or bound in plan.get("deletedResources", []):
        return {}
    try:
        resource = resolve_workflow_resource(
            user, policy, bound, workflow, history=True
        )
        if resource.status != "active":
            return {}
        return feature_display_attributes(resource, feature_ids)
    except (PermissionDenied, DataQueryError):
        return {}
