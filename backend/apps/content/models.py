from django.conf import settings
from django.db import models
from apps.projects.scoping import ProjectScopedModel


class Article(ProjectScopedModel):
    kind = models.CharField(
        max_length=16, choices=[("knowledge", "科普知识"), ("news", "团队动态")]
    )
    title = models.CharField(max_length=180)
    summary = models.CharField(max_length=800, blank=True)
    category = models.CharField(max_length=80)
    body = models.TextField(blank=True)
    status = models.CharField(
        max_length=16,
        default="draft",
        choices=[("draft", "草稿"), ("published", "已发布"), ("archived", "已下架")],
    )
    source = models.TextField(blank=True)
    links = models.JSONField(default=list, blank=True)
    event_date = models.DateField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    cover_asset = models.ForeignKey(
        "Asset",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="covered_articles",
    )
    pinned = models.BooleanField(default=False)
    revision = models.PositiveIntegerField(default=1)
    seed_key = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ("-pinned", "-published_at", "-id")
        indexes = [models.Index(fields=("project_tag", "kind", "status"))]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(project_tag_id=1),
                name="content_article_public_project",
            ),
            models.UniqueConstraint(
                fields=("project_tag", "seed_key"),
                condition=~models.Q(seed_key=""),
                name="unique_content_seed",
            ),
        ]


class Asset(ProjectScopedModel):
    article = models.ForeignKey(
        Article, on_delete=models.CASCADE, related_name="assets"
    )
    name = models.CharField(max_length=255)
    path = models.CharField(max_length=500)
    mime_type = models.CharField(max_length=80)
    caption = models.CharField(max_length=500, blank=True)
    checksum = models.CharField(max_length=64)
    size_bytes = models.PositiveBigIntegerField()
    pending_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pending_content_assets",
    )
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ("id",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(project_tag_id=1),
                name="content_asset_public_project",
            ),
        ]
