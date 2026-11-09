"""Project-bound flow registrations and immutable published definitions."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.projects.scoping import ProjectScopedModel


class BusinessFlowDefinition(ProjectScopedModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    current_version = models.ForeignKey(
        "BusinessFlowVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "code"), name="business_flow_project_code"
            )
        ]

    def save(self, *args, **kwargs):
        if self.current_version_id is not None:
            parent = (
                BusinessFlowVersion.objects.filter(pk=self.current_version_id)
                .values_list("flow_id", flat=True)
                .first()
            )
            if parent != self.pk:
                raise ValidationError("当前版本必须属于同一业务流")
        return super().save(*args, **kwargs)


class BusinessFlowVersion(models.Model):
    flow = models.ForeignKey(
        BusinessFlowDefinition, on_delete=models.PROTECT, related_name="versions"
    )
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=16, default="published")
    definition = models.JSONField(default=dict)
    definition_hash = models.CharField(max_length=64)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-version", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("flow", "version"), name="business_flow_version_number"
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("已发布业务流版本不可修改，请发布新版本")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("已发布业务流版本不可删除，可停用业务流")
