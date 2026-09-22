from apps.projects.scoping import ProjectScopedModel
from django.conf import settings
from django.db import models


class OperationLog(ProjectScopedModel):
    class Status(models.TextChoices):
        SUCCESS = "success", "成功"
        WARNING = "warning", "告警"
        FAILED = "failed", "失败"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="操作用户",
    )
    module = models.CharField(max_length=64, verbose_name="模块")
    action = models.CharField(max_length=64, verbose_name="操作")
    event_code = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        verbose_name="稳定事件编码",
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, verbose_name="结果"
    )
    target_type = models.CharField(max_length=64, blank=True, verbose_name="目标类型")
    target_id = models.PositiveBigIntegerField(
        null=True, blank=True, verbose_name="目标后台 ID"
    )
    target_code = models.CharField(max_length=128, blank=True, verbose_name="目标编码")
    target_name = models.CharField(max_length=255, blank=True, verbose_name="目标名称")
    message = models.TextField(blank=True, verbose_name="说明")
    ip_address = models.GenericIPAddressField(
        null=True, blank=True, verbose_name="IP 地址"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="操作时间")

    class Meta:
        verbose_name = "操作日志"
        verbose_name_plural = "操作日志"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("module", "action")),
            models.Index(fields=("target_type", "target_id")),
            models.Index(fields=("created_at",)),
        ]

    def __str__(self) -> str:
        return f"{self.module}.{self.action} {self.status}"


class UserActivityHour(ProjectScopedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="activity_hours",
        verbose_name="活跃用户",
    )
    bucket_start = models.DateTimeField(verbose_name="小时起始时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="记录时间")

    class Meta:
        verbose_name = "用户小时活跃记录"
        verbose_name_plural = "用户小时活跃记录"
        ordering = ("-bucket_start",)
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "user", "bucket_start"),
                name="audit_activity_user_hour_unique",
            )
        ]
        indexes = [models.Index(fields=("bucket_start",))]

    def __str__(self) -> str:
        return f"{self.user_id}@{self.bucket_start.isoformat()}"
