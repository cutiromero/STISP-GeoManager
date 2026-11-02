from django.conf import settings
from django.db import models
import uuid
from apps.projects.scoping import ProjectScopedModel

ACTIVE = ("queued", "running")


class AgentPolicy(models.Model):
    singleton = models.PositiveSmallIntegerField(primary_key=True, default=1)
    value = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)


class AgentRuntime(models.Model):
    name = models.CharField(max_length=80, primary_key=True)
    heartbeat = models.DateTimeField(null=True)
    detail = models.JSONField(default=dict)


class Conversation(ProjectScopedModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    mode = models.CharField(
        max_length=10, choices=[("chat", "chat"), ("agent", "agent")]
    )
    title = models.CharField(max_length=120, default="新会话")
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at", "-id")


class AgentAttachment(ProjectScopedModel):
    """A project-scoped file supplied to one agent conversation.

    The file itself is kept below the TOML-configured business-data root.  The
    model stores only a relative path and bounded derived text; it never makes
    an uploaded path available to the model or browser.
    """

    KIND_CHOICES = (("document", "文档"), ("image", "图片"))

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="attachments"
    )
    name = models.CharField(max_length=255)
    path = models.CharField(max_length=500)
    mime_type = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    size_bytes = models.PositiveBigIntegerField(default=0)
    checksum = models.CharField(max_length=64)
    extracted_text = models.TextField(blank=True)
    extraction_status = models.CharField(max_length=16, default="ready")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("conversation", "checksum"),
                name="agent_attachment_conversation_checksum",
            )
        ]


class AgentRun(ProjectScopedModel):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="runs"
    )
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    model = models.CharField(max_length=80)
    thinking_mode = models.CharField(max_length=8, default="fast")
    reasoning_effort = models.CharField(
        max_length=8, blank=True, default="", db_default=""
    )
    budget_profile = models.CharField(
        max_length=16, blank=True, default="", db_default=""
    )
    budget_snapshot = models.JSONField(default=dict, db_default={})
    prompt = models.TextField()
    answer = models.TextField(blank=True)
    status = models.CharField(max_length=16, default="queued", db_index=True)
    detail = models.CharField(max_length=300, blank=True)
    idempotency_key = models.CharField(max_length=80)
    resource_ids = models.JSONField(default=list)
    knowledge_selection = models.JSONField(default=dict, db_default={})
    algorithm_selection_mode = models.CharField(
        max_length=8, default="auto", db_default="auto"
    )
    algorithm_version_ids = models.JSONField(default=list, db_default=[])
    data_selection_mode = models.CharField(
        max_length=8, default="auto", db_default="auto"
    )
    attachment_ids = models.JSONField(default=list)
    internet_enabled = models.BooleanField(default=False)
    evidence = models.JSONField(default=list)
    compute_intent = models.JSONField(default=dict, db_default={})
    research_intent = models.JSONField(default=dict, db_default={})
    interaction = models.JSONField(default=dict, db_default={})
    interaction_history = models.JSONField(default=list, db_default=[])
    execution_state = models.JSONField(default=dict, db_default={})
    research_workflow = models.ForeignKey(
        "AgentWorkflow",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_runs",
    )
    context_truncated = models.BooleanField(default=False)
    cancel_requested = models.BooleanField(default=False)
    heartbeat = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("conversation", "idempotency_key"), name="agent_run_idempotency"
            ),
            models.UniqueConstraint(
                fields=("conversation",),
                condition=models.Q(status__in=ACTIVE),
                name="agent_one_active_conversation",
            ),
        ]


class RunEvent(models.Model):
    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=24)
    text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("id",)


WORKFLOW_ACTIVE = ("queued", "running", "waiting_compute", "waiting_approval", "paused")


class AgentWorkflow(ProjectScopedModel):
    """Durable, project-scoped research workflow independent of chat history."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    workflow_type = models.CharField(
        max_length=40, default="hyperspectral_interpretation"
    )
    goal = models.TextField()
    model = models.CharField(max_length=80)
    status = models.CharField(max_length=24, default="queued", db_index=True)
    detail = models.CharField(max_length=300, blank=True)
    current_step = models.CharField(max_length=80, blank=True)
    iteration = models.PositiveIntegerField(default=0)
    operator_steps = models.PositiveIntegerField(default=0)
    max_iterations = models.PositiveIntegerField(default=5)
    max_operator_steps = models.PositiveIntegerField(default=8)
    execute_operators = models.BooleanField(default=False)
    resource_ids = models.JSONField(default=list)
    algorithm_version_id = models.PositiveBigIntegerField(null=True, blank=True)
    parameters = models.JSONField(default=dict)
    result_ids = models.JSONField(default=list)
    evidence = models.JSONField(default=list)
    policy_snapshot = models.JSONField(default=dict)
    plan = models.JSONField(default=dict, db_default={})
    plan_hash = models.CharField(max_length=64, blank=True, db_default="")
    import_results = models.BooleanField(default=True, db_default=True)
    result_resource_ids = models.JSONField(default=list, db_default=[])
    cancel_requested = models.BooleanField(default=False)
    pause_requested = models.BooleanField(default=False, db_default=False)
    paused_from = models.CharField(max_length=24, blank=True, default="", db_default="")
    idempotency_key = models.CharField(max_length=80)
    heartbeat = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "project_tag", "idempotency_key"),
                name="agent_workflow_idempotency",
            ),
            models.UniqueConstraint(
                fields=("owner",),
                condition=models.Q(status__in=WORKFLOW_ACTIVE),
                name="agent_one_active_workflow_user",
            ),
        ]


class AgentWorkflowStep(models.Model):
    workflow = models.ForeignKey(
        AgentWorkflow, on_delete=models.CASCADE, related_name="steps"
    )
    sequence = models.PositiveIntegerField()
    kind = models.CharField(max_length=64)
    status = models.CharField(max_length=24, default="running")
    message = models.CharField(max_length=500, blank=True)
    action = models.JSONField(default=dict)
    input_refs = models.JSONField(default=dict)
    output_refs = models.JSONField(default=dict)
    metrics = models.JSONField(default=dict)
    compute_task_id = models.UUIDField(null=True, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("sequence",)
        constraints = [
            models.UniqueConstraint(
                fields=("workflow", "sequence"), name="agent_workflow_step_sequence"
            )
        ]


class AgentCheckpoint(models.Model):
    workflow = models.ForeignKey(
        AgentWorkflow, on_delete=models.CASCADE, related_name="checkpoints"
    )
    node = models.CharField(max_length=80)
    state = models.JSONField(default=dict)
    state_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-id",)


class AgentComputeFollowup(models.Model):
    """Durable compute/import intent; the task remains the source of truth."""

    run = models.ForeignKey(
        AgentRun, on_delete=models.CASCADE, related_name="compute_followups"
    )
    task = models.OneToOneField(
        "compute.ComputeTask", on_delete=models.CASCADE, related_name="agent_followup"
    )
    auto_import = models.BooleanField(default=False)
    output_keys = models.JSONField(default=list)
    import_name = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=24, default="waiting_compute", db_index=True)
    detail = models.CharField(max_length=300, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
