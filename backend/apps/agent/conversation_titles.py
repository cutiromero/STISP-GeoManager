from __future__ import annotations

from pathlib import Path

from django.utils import timezone

from apps.catalog.models import DataResource
from apps.compute.project_tools import GEOLOGY_PROJECT_CODES
from apps.projects.models import Project
from .models import WorkflowUpload


DEFAULT_LOGIC_PROMPT = (
    "请检查这些资料的岩性、构造与蚀变关系，识别不一致之处，给出处置建议并生成对比成果。"
)
TITLE_NAME_LIMIT = 28


def default_logic_title(title):
    return title == "新会话" or title.startswith(DEFAULT_LOGIC_PROMPT)


def logic_title(run):
    if not Project.objects.filter(
        pk=run.project_tag_id, code__in=GEOLOGY_PROJECT_CODES
    ).exists():
        return None
    intent = run.research_intent or {}
    batch = intent.get("_uploadBatchId")
    uploads = (
        WorkflowUpload.objects.filter(
            owner_id=run.owner_id, project_tag_id=run.project_tag_id, batch_id=batch
        ).select_related("resource")
        if batch
        else []
    )
    candidates = sorted(
        uploads, key=lambda upload: (upload.role_hint != "lithology", upload.id)
    )
    resource = (
        candidates[0].resource
        if candidates
        else DataResource.objects.filter(
            project_tag_id=run.project_tag_id, pk__in=run.resource_ids
        )
        .order_by("id")
        .first()
    )
    name = Path(resource.name).stem if resource else "地质资料"
    name = " ".join(name.split())[:TITLE_NAME_LIMIT]
    when = timezone.localtime(run.created_at)
    return f"{name} 岩性·构造·蚀变检查 {when:%m-%d %H:%M} #{run.id}"


def update_logic_title(run, *, allow_new=True):
    conversation = run.conversation
    if not default_logic_title(conversation.title) or (
        not allow_new and conversation.title == "新会话"
    ):
        return False
    title = logic_title(run)
    if title is None:
        return False
    conversation.title = title
    conversation.save(update_fields=["title"])
    return True
