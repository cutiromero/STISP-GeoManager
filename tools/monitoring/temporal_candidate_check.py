"""Exercise real RF and native observations inside the standard release candidate."""

import argparse
import json
from pathlib import Path
import runpy

# CONFIGURATION
CHECKS = ["tools/spartina/candidate_check.py", "tools/wildfire/candidate_check.py"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", type=Path, required=True)
    options = parser.parse_args()
    context = json.loads(options.context.read_text())
    code = Path(context["code"]).resolve()
    root = Path(context["root"]).resolve()
    assert code.is_relative_to(root)
    for relative in CHECKS:
        runpy.run_path(str(code / relative), run_name="__main__")
    from django.contrib.auth import get_user_model
    from django.db import transaction
    from apps.catalog.models import DataResource
    from apps.catalog.monitoring_metadata import update_metadata
    from apps.ecology.source_catalog import monitoring_sources, source_times
    from apps.projects.context import project_scope, ProjectScope
    from apps.projects.models import Project

    actor = get_user_model().objects.get(username="admin")
    project = Project.objects.get(code="06")
    with (
        project_scope(ProjectScope((project.pk,), project.pk, actor.pk, True)),
        transaction.atomic(),
    ):
        rf_sources = list(
            DataResource.objects.filter(
                code__startswith="spartina-candidate-"
            ).order_by("code")
        )
        assert len(rf_sources) == 3
        for source, month in zip(rf_sources, [3, 8, 12]):
            update_metadata(
                actor,
                source,
                {
                    "usages": [{"scene": "spartina", "purpose": "input"}],
                    "collectionKey": "candidate-dynamic-rf",
                    "precision": "month",
                    "startsAt": f"2025-{month:02d}-01",
                    "endsAt": f"2025-{month:02d}-31",
                },
            )
        catalog = monitoring_sources(
            actor, "spartina", collection="candidate-dynamic-rf"
        )
        assert catalog["inputSets"] and set(
            catalog["inputSets"][0]["inputs"].values()
        ) == {source.pk for source in rf_sources}
        cubes = list(
            DataResource.objects.filter(
                file_format="ZARR", code__startswith="wildfire-seasfire-cube-candidate"
            )
        )
        assert len(cubes) == 1
        update_metadata(
            actor,
            cubes[0],
            {
                "usages": [{"scene": "wildfire", "purpose": "input"}],
                "collectionKey": "candidate-native",
            },
        )
        native = monitoring_sources(actor, "wildfire", collection="candidate-native")
        assert native["assets"][0]["metadata"]["sourceSchema"]["timeCount"] == 966
        page = source_times(actor, "wildfire", cubes[0].pk, 2019, "gwis_ba")
        assert page["items"] and page["items"][-1]["endDate"] == "2019-12-31"
        transaction.set_rollback(True)
    print(
        json.dumps(
            {
                "accepted": True,
                "checks": {
                    "rfRealInference": True,
                    "wildfireRealObservation": True,
                    "dynamicSources": True,
                    "actualTimeIndex": True,
                },
            }
        )
    )


if __name__ == "__main__":
    main()
