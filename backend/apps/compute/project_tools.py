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
    return query.filter(own | common | shared)
