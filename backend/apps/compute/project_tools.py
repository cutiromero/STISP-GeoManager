"""Reuse shared tools by research topic without changing historical task access."""

from django.db.models import Q

from apps.projects.models import Project

GEOLOGY_PROJECT_CODES = ("02", "demo-geology-reasoning")


def topic_algorithms(query, selected_id):
    project = Project.objects.filter(pk=selected_id, is_active=True).first()
    if project is None or project.code == "default":
        return query
    # An algorithm registered within this project is an explicit local choice.
    own = Q(project_tag_id=selected_id)
    common = Q(identifier__in=("vector-metrics", "vector-geometry-repair"))
    if project.code in GEOLOGY_PROJECT_CODES:
        shared = (
            Q(identifier__startswith="geology-")
            | Q(category__icontains="地质")
            | Q(category__icontains="逻辑推理")
        )
    elif project.code == "demo-arid-ecology":
        shared = (
            Q(
                identifier__in=(
                    "raster-ndvi",
                    "raster-ndwi",
                    "ndvi-change",
                    "ecology-priority",
                )
            )
            | Q(identifier__startswith="ecology-")
            | Q(category__icontains="生态")
            | Q(category__icontains="植被")
        )
    else:
        return query
    # Published conversion capabilities are domain-neutral shared tools. Their
    # declaration does not widen the enclosing public/current-project scope.
    from django.db.models import Exists, OuterRef
    from .models import AlgorithmVersion

    query = query.alias(
        _input_adapter=Exists(
            AlgorithmVersion.objects.filter(
                Q(manifest__inputAdapter__isnull=False)
                | Q(manifest__inputScriptBridge__isnull=False),
                algorithm_id=OuterRef("pk"),
                status="published",
            )
        )
    )
    common |= Q(_input_adapter=True)
    return query.filter(own | common | shared)
