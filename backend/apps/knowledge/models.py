from django.conf import settings
from django.db import models

from apps.projects.scoping import ProjectScopedModel


class KnowledgeEntry(ProjectScopedModel):
    seed_key = models.CharField(max_length=100, blank=True)
    title = models.CharField(max_length=180)
    category = models.CharField(max_length=80)
    subject = models.CharField(max_length=120)
    predicate = models.CharField(max_length=120)
    object = models.CharField(max_length=120)
    statement = models.TextField()
    explanation = models.TextField(blank=True)
    conditions = models.JSONField(default=list)
    exceptions = models.JSONField(default=list)
    aliases = models.JSONField(default=list)
    sources = models.JSONField(default=list)
    status = models.CharField(max_length=16, default="draft")
    rule_kind = models.CharField(max_length=32, default="none")
    rule_config = models.JSONField(default=dict)
    revision = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ("category", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "seed_key"),
                condition=~models.Q(seed_key=""),
                name="unique_knowledge_seed",
            )
        ]
        indexes = [models.Index(fields=("project_tag", "status", "category"))]


class KnowledgeRevision(ProjectScopedModel):
    entry = models.ForeignKey(
        KnowledgeEntry, on_delete=models.CASCADE, related_name="versions"
    )
    revision = models.PositiveIntegerField()
    snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("entry", "revision"), name="unique_knowledge_revision"
            )
        ]


class KnowledgeLibrary(ProjectScopedModel):
    """A separate upstream KB for every project/owner permission domain."""

    scope_key = models.CharField(max_length=100, unique=True)
    visibility = models.CharField(max_length=16, default="project")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT
    )
    upstream_kb_id = models.CharField(max_length=100, blank=True)
    provisioning = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class KnowledgeDocument(ProjectScopedModel):
    library = models.ForeignKey(KnowledgeLibrary, on_delete=models.PROTECT)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    title = models.CharField(max_length=180)
    filename = models.CharField(max_length=255)
    source_url = models.URLField(max_length=2000, blank=True)
    visibility = models.CharField(max_length=16, default="project")
    sha256 = models.CharField(max_length=64)
    original_path = models.CharField(max_length=500)
    extracted_path = models.CharField(max_length=500, blank=True)
    upstream_document_id = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=16, default="pending")
    detail = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_checked_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ("-id",)
        constraints = [
            models.UniqueConstraint(
                fields=("library", "sha256"), name="knowledge_document_hash"
            )
        ]
