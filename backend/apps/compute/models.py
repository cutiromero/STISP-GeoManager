import uuid

from django.conf import settings
from django.db import models

from apps.projects.scoping import ProjectScopedModel


class AlgorithmCategory(ProjectScopedModel):
    name = models.CharField(max_length=80)
    sort_order = models.PositiveIntegerField(default=100)

    class Meta:
        ordering = ("sort_order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "name"), name="compute_category_project_name"
            )
        ]


class AlgorithmResource(ProjectScopedModel):
    identifier = models.SlugField(max_length=80)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=80, blank=True)
    author = models.CharField(max_length=160, blank=True)
    enabled = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "identifier"),
                name="compute_algorithm_project_identifier",
            )
        ]
        permissions = [
            ("manage_algorithms", "登记和维护算法"),
            ("publish_algorithm", "发布算法版本"),
            ("download_algorithm", "下载算法源码包"),
        ]


class AlgorithmVersion(models.Model):
    algorithm = models.ForeignKey(
        AlgorithmResource, on_delete=models.PROTECT, related_name="versions"
    )
    version = models.CharField(max_length=40)
    manifest = models.JSONField(default=dict)
    checksum = models.CharField(max_length=64)
    package_path = models.CharField(max_length=255)
    runtime_digest = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=16, default="draft")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("algorithm", "version"), name="compute_unique_version"
            )
        ]
        ordering = ("-id",)


class ComputeTask(ProjectScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    version = models.ForeignKey(AlgorithmVersion, on_delete=models.PROTECT)
    parameters = models.JSONField(default=dict)
    status = models.CharField(max_length=16, default="queued", db_index=True)
    stage = models.CharField(max_length=200, default="等待计算资源")
    progress = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    trial = models.BooleanField(default=False)
    unread = models.BooleanField(default=False)
    idempotency_key = models.CharField(max_length=80)
    request_hash = models.CharField(max_length=64)
    retry_of = models.ForeignKey("self", on_delete=models.PROTECT, null=True)
    attempt_token = models.CharField(max_length=40, blank=True)
    heartbeat = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "project_tag", "idempotency_key"),
                name="compute_task_idempotence",
            )
        ]
        permissions = [
            ("submit_task", "提交计算任务"),
            ("view_own_task", "查看本人计算"),
            ("cancel_own_task", "取消本人计算"),
            ("manage_tasks", "管理项目计算任务"),
        ]


class ComputeInput(models.Model):
    task = models.ForeignKey(
        ComputeTask, on_delete=models.CASCADE, related_name="input_records"
    )
    key = models.CharField(max_length=80)
    resource = models.ForeignKey("catalog.DataResource", on_delete=models.PROTECT)
    snapshot = models.JSONField(default=dict)
    checksum = models.CharField(max_length=64, blank=True)


class ComputeAttempt(models.Model):
    task = models.ForeignKey(
        ComputeTask, on_delete=models.CASCADE, related_name="attempts"
    )
    token = models.CharField(max_length=40, unique=True)
    container_name = models.CharField(max_length=80)
    runtime_digest = models.CharField(max_length=100)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)
    status = models.CharField(max_length=16, default="running")


class ComputeOutput(models.Model):
    task = models.ForeignKey(
        ComputeTask, on_delete=models.PROTECT, related_name="outputs"
    )
    key = models.CharField(max_length=80)
    label = models.CharField(max_length=160)
    kind = models.CharField(max_length=16)
    file_name = models.CharField(max_length=160)
    path = models.CharField(max_length=255)
    size_bytes = models.PositiveBigIntegerField()
    checksum = models.CharField(max_length=64)
    metadata = models.JSONField(default=dict)
    expired = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("task", "key"), name="compute_unique_output"
            )
        ]


class ComputeImport(models.Model):
    storage_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    output = models.OneToOneField(
        ComputeOutput, on_delete=models.PROTECT, related_name="import_record"
    )
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    name = models.CharField(max_length=160)
    status = models.CharField(max_length=16, default="queued")
    error = models.TextField(blank=True)
    resource = models.ForeignKey(
        "catalog.DataResource", null=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)
    heartbeat = models.DateTimeField(null=True)


class RuntimeLease(models.Model):
    name = models.CharField(max_length=80, primary_key=True)
    token = models.CharField(max_length=40, blank=True)
    heartbeat = models.DateTimeField(null=True)
    detail = models.JSONField(default=dict)
