from types import SimpleNamespace
from unittest.mock import Mock

from apps.agent import review_map_warmup as warmup
from apps.agent import models, workflow, workflow_resources


def test_cache_warmup_waits_for_commit_and_only_reads_authorized_unique_resources(
    monkeypatch,
):
    callbacks = []
    monkeypatch.setattr(warmup.transaction, "on_commit", callbacks.append)
    close = Mock()
    monkeypatch.setattr(warmup, "close_old_connections", close)
    saved = SimpleNamespace(
        project_tag_id=3,
        owner_id=2,
        cancel_requested=False,
        pause_requested=False,
        status="running",
    )
    monkeypatch.setattr(
        models.AgentWorkflow._base_manager, "get", Mock(return_value=saved)
    )
    monkeypatch.setattr(
        models.AgentWorkflow.objects,
        "filter",
        Mock(
            return_value=Mock(
                exclude=Mock(return_value=Mock(exists=Mock(return_value=True)))
            )
        ),
    )
    actor = Mock(return_value=("owner", {}))
    monkeypatch.setattr(workflow, "_authorize", actor)
    resolve = Mock(side_effect=lambda user, policy, identity, task: identity)
    monkeypatch.setattr(workflow_resources, "resolve_workflow_resource", resolve)
    render = Mock()
    monkeypatch.setattr(warmup, "prewarm_display_geometry", render)
    started = []

    def thread(**options):
        assert options["daemon"] is True

        def start():
            started.append(True)
            options["target"](*options["args"])

        return SimpleNamespace(start=start)

    monkeypatch.setattr(warmup.threading, "Thread", thread)
    warmup.warm_review_background("workflow", [501, 502, 501])
    assert len(callbacks) == 1 and not started and not actor.called
    callbacks[0]()
    assert started and actor.call_count == 2 and resolve.call_count == 2
    assert [call.args[0] for call in render.call_args_list] == [501, 502]
    assert close.call_count == 2


def test_busy_display_cache_never_blocks_or_starts_more_work(monkeypatch):
    monkeypatch.setattr(warmup.transaction, "on_commit", lambda callback: callback())
    thread = Mock()
    monkeypatch.setattr(warmup.threading, "Thread", thread)
    assert warmup._SLOT.acquire(blocking=False)
    try:
        warmup.warm_review_background("workflow", [501])
    finally:
        warmup._SLOT.release()
    assert not thread.called
