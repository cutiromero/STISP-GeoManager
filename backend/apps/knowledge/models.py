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
