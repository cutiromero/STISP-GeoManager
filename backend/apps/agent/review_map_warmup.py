"""Warm private display geometry while model/compute work proceeds independently."""

import threading

from django.db import close_old_connections, transaction

from apps.catalog.display_geometry import prewarm_display_geometry
from apps.projects.context import ProjectScope, project_scope

_SLOT = threading.BoundedSemaphore(1)


def warm_review_background(workflow_id, resource_ids):
    """At most one read-only cache job per worker process; never delay the graph."""

    def start():
        if not _SLOT.acquire(blocking=False):
            return
        thread = threading.Thread(
            target=_warm,
            args=(workflow_id, tuple(dict.fromkeys(resource_ids))),
            daemon=True,
            name="logic-review-display-cache",
        )
        try:
            thread.start()
        except Exception:
            _SLOT.release()
            return

    transaction.on_commit(start)


def _warm(workflow_id, resource_ids):
    from .models import AgentWorkflow
    from .workflow import _authorize
    from .workflow_resources import resolve_workflow_resource

    close_old_connections()
    try:
        workflow = AgentWorkflow._base_manager.get(pk=workflow_id)
        if (
            workflow.cancel_requested
            or workflow.pause_requested
            or workflow.status in {"cancelled", "failed", "interrupted"}
        ):
            return
        with project_scope(
            ProjectScope(
                (workflow.project_tag_id,), workflow.project_tag_id, workflow.owner_id
            )
        ):
            for identity in resource_ids:
                if (
                    AgentWorkflow.objects.filter(
                        pk=workflow_id, cancel_requested=False, pause_requested=False
                    )
                    .exclude(status__in=["cancelled", "failed", "interrupted"])
                    .exists()
                ):
                    user, policy = _authorize(workflow)
                    resource = resolve_workflow_resource(
                        user, policy, identity, workflow
                    )
                    prewarm_display_geometry(resource)
                else:
                    return
    except Exception:
        # Display caching is optional. The map's authorized read can retry it.
        return
    finally:
        close_old_connections()
        _SLOT.release()
