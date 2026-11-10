from django.db.models import Case, F, IntegerField, Q, TextField, Value, When

from .tools import brief


DESCRIPTION_LIMIT = 800
GENERATED_DESCRIPTIONS = ("计算结果；任务 ", "MH-workflow任务资料，原文件：")


def search_terms(text):
    return list(dict.fromkeys(text[:200].split()))


def search_resources(query, text):
    generated = Q()
    for prefix in GENERATED_DESCRIPTIONS:
        generated |= Q(description__startswith=prefix)
    query = query.annotate(
        _search_description=Case(
            When(generated, then=Value("")),
            default=F("description"),
            output_field=TextField(),
        )
    )
    terms = search_terms(text)
    if terms:
        all_names, any_name = Q(), Q()
        for term in terms:
            name = Q(name__icontains=term)
            query = query.filter(name | Q(_search_description__icontains=term))
            all_names &= name
            any_name |= name
        query = query.annotate(
            _search_rank=Case(
                When(all_names, then=Value(0)),
                When(any_name, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        ).order_by("_search_rank", "-updated_at", "-created_at", "-id")
    else:
        query = query.order_by("-updated_at", "-created_at", "-id")
    return query


def description_excerpt(description, terms):
    if not terms:
        return description[:DESCRIPTION_LIMIT]
    lowered = description.lower()
    matched = [(lowered.find(term.lower()), len(term)) for term in terms]
    matched = [(start, size) for start, size in matched if start >= 0]
    if not matched:
        return description[:DESCRIPTION_LIMIT]
    context = min(
        32,
        max(
            0,
            (DESCRIPTION_LIMIT - sum(size + 3 for _, size in matched))
            // (2 * len(matched)),
        ),
    )
    windows = []
    for start, size in sorted(matched):
        left, right = (
            max(0, start - context),
            min(len(description), start + size + context),
        )
        if windows and left <= windows[-1][1]:
            windows[-1] = (windows[-1][0], max(right, windows[-1][1]))
        else:
            windows.append((left, right))
    excerpt = "…".join(description[left:right] for left, right in windows)
    return (
        ("…" if windows[0][0] else "")
        + excerpt
        + ("…" if windows[-1][1] < len(description) else "")
    )


def search_brief(resource, text):
    value = brief(resource)
    missing = [
        term for term in search_terms(text) if term.lower() not in resource.name.lower()
    ]
    description = resource._search_description if missing else resource.description
    value["description"] = description_excerpt(description, missing)
    return value
