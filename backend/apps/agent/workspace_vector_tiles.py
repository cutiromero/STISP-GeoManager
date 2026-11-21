"""Prepare reusable display tiles outside agent responses and map requests."""

import logging
import threading

from django.db import close_old_connections, transaction

from apps.catalog.vector_tiles import prepare_vector_tiles
from apps.core.permissions import has_feature_perm
from apps.core.storage import app_path
from apps.core.storage_locks import StorageLockTimeout, storage_lock
from apps.projects.context import ProjectScope, project_scope

from .models import AgentRun
from .policy import fresh_user, require_access

logger = logging.getLogger(__name__)
_WORKSPACE_TILE_SLOT = threading.BoundedSemaphore(1)


def schedule_workspace_vector_tiles(run_id, resource_ids):
    def start():
        if not _WORKSPACE_TILE_SLOT.acquire(blocking=False):
            return
        thread = threading.Thread(
            target=_prepare,
            args=(run_id, tuple(resource_ids)),
            daemon=True,
            name="agent-workspace-vector-tiles",
        )
        try:
            thread.start()
        except RuntimeError:
            _WORKSPACE_TILE_SLOT.release()
            logger.warning("无法启动工程矢量瓦片准备 run=%s", run_id, exc_info=True)

    transaction.on_commit(start)


def _prepare(run_id, resource_ids):
    from .map_tools import scope_resources

    close_old_connections()
    try:
        run = AgentRun._base_manager.filter(pk=run_id, cancel_requested=False).first()
        if run is None:
            return
        with project_scope(
            ProjectScope((run.project_tag_id,), run.project_tag_id, run.owner_id)
        ):
            user = fresh_user(run.owner_id)
            policy = require_access(user, "agent", run.model)
            if not policy.get("mapDisplayEnabled", True) or not has_feature_perm(
                user, "core.query_data"
            ):
                return
            for resource in scope_resources(run, user, policy, list(resource_ids)):
                lock = app_path(
                    "cache", "vector-tiles", "locks", f"{resource.id % 256}.lock"
                )
                try:
                    with storage_lock(lock, wait=False):
                        prepare_vector_tiles(resource)
                except StorageLockTimeout:
                    continue
                except Exception:
                    logger.warning(
                        "工程矢量瓦片准备失败 resource=%s", resource.id, exc_info=True
                    )
    except Exception:
        logger.warning("工程矢量瓦片准备已退出 run=%s", run_id, exc_info=True)
    finally:
        close_old_connections()
        _WORKSPACE_TILE_SLOT.release()
