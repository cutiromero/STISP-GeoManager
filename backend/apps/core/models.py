from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="用户",
    )
    avatar_url = models.URLField(blank=True, verbose_name="头像 URL")
    avatar_data = models.BinaryField(blank=True, null=True, verbose_name="头像数据")
    avatar_content_type = models.CharField(
        max_length=50, blank=True, verbose_name="头像内容类型"
    )
    department = models.CharField(max_length=120, blank=True, verbose_name="部门")
    normalized_email = models.EmailField(
        max_length=254,
        unique=True,
        null=True,
        blank=True,
        verbose_name="规范化邮箱",
    )
    disabled_permissions = models.JSONField(
        default=list,
        blank=True,
        verbose_name="用户主动关闭的权限",
    )
    operation_log_group_ids = models.JSONField(
        default=list,
        blank=True,
        verbose_name="可查看日志角色",
    )
    allow_public_project = models.BooleanField(
        default=True, verbose_name="允许访问公开项目"
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "用户资料"
        verbose_name_plural = "用户资料"

    def __str__(self):
        return self.user.get_username()


class RoleApplication(models.Model):
    class RequestedRole(models.TextChoices):
        RESEARCH = "research", "科研用户"

    class Status(models.TextChoices):
        PENDING = "pending", "待审核"
        APPROVED = "approved", "已通过"
        REJECTED = "rejected", "已拒绝"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="role_application",
        verbose_name="申请用户",
    )
    requested_role = models.CharField(
        max_length=24,
        choices=RequestedRole.choices,
        default=RequestedRole.RESEARCH,
        verbose_name="申请角色",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="申请状态",
    )
    reason = models.TextField(verbose_name="申请说明")
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_role_applications",
        verbose_name="审核人",
    )
    review_note = models.TextField(blank=True, verbose_name="审核说明")
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name="审核时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="申请时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "角色申请"
        verbose_name_plural = "角色申请"
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("status", "created_at"),
                name="core_roleap_status_97a9dc_idx",
            )
        ]

    def __str__(self):
        return f"{self.user.get_username()} -> {self.get_requested_role_display()}"


class FeaturePermission(models.Model):
    class Meta:
        verbose_name = "平台功能权限"
        verbose_name_plural = "平台功能权限"
        default_permissions = ()
        permissions = [
            ("manage_feature_permissions", "可配置功能权限"),
            ("create_user", "可新建用户"),
            ("view_operation_logs", "可查看操作日志"),
            ("view_all_operation_logs", "可查看所有用户日志"),
            ("view_own_operation_logs", "可查看自己的日志"),
            ("view_group_operation_logs", "可查看指定角色日志"),
            ("manage_system_settings", "可修改系统设置"),
            ("manage_data_backup", "可管理数据备份"),
            ("manage_auth", "可修改认证授权"),
            ("view_dashboard_resource_card", "可查看 Dashboard 数据资源卡片"),
            ("view_dashboard_layer_card", "可查看 Dashboard 图层数卡片"),
            ("view_dashboard_raster_card", "可查看 Dashboard 栅格数量卡片"),
            ("view_dashboard_user_card", "可查看 Dashboard 用户数量卡片"),
            ("view_dashboard_active_users_card", "可查看 Dashboard 活跃用户卡片"),
            ("view_dashboard_system_card", "可查看 Dashboard 系统信息"),
            ("browse_data", "可浏览数据"),
            ("query_data", "可查询数据"),
            ("load_vector_layer", "可加载矢量图层"),
            ("load_raster_layer", "可加载栅格图层"),
            ("custom_symbolization", "可自定义符号化"),
            ("ai_interpretation", "可使用 AI 智能解译"),
            ("use_local_model", "可使用本地模型对话"),
            ("use_data_agent", "可使用数据智能体"),
        ]


class SystemSetting(models.Model):
    allow_registration = models.BooleanField(default=True, verbose_name="开放自助注册")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "系统设置"
        verbose_name_plural = "系统设置"

    def __str__(self):
        return "系统设置"


class BackupRun(models.Model):
    class PlanType(models.TextChoices):
        PLATFORM = "platform", "平台数据"
        RESEARCH = "research", "科研数据"

    class TargetType(models.TextChoices):
        LOCAL = "local", "本地目录"
        OBJECT_STORAGE = "object_storage", "对象存储"

    class Trigger(models.TextChoices):
        MANUAL = "manual", "手动触发"
        SCHEDULED = "scheduled", "计划触发"

    class Status(models.TextChoices):
        QUEUED = "queued", "等待中"
        RUNNING = "running", "运行中"
        SUCCESS = "success", "成功"
        FAILED = "failed", "失败"

    plan_type = models.CharField(
        max_length=16, choices=PlanType.choices, verbose_name="备份类型"
    )
    target_type = models.CharField(
        max_length=32, choices=TargetType.choices, verbose_name="备份目标"
    )
    trigger = models.CharField(
        max_length=16, choices=Trigger.choices, verbose_name="触发方式"
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.QUEUED,
        verbose_name="任务状态",
    )
    progress_percent = models.PositiveSmallIntegerField(
        default=0, verbose_name="进度百分比"
    )
    messages = models.JSONField(default=list, blank=True, verbose_name="任务消息")
    result = models.JSONField(null=True, blank=True, verbose_name="任务结果")
    error_message = models.TextField(blank=True, verbose_name="错误信息")
    archive_name = models.CharField(max_length=255, blank=True, verbose_name="归档名")
    size_bytes = models.PositiveBigIntegerField(default=0, verbose_name="归档大小")
    checksum_sha256 = models.CharField(
        max_length=64, blank=True, verbose_name="SHA256 校验值"
    )
    object_key = models.CharField(max_length=1024, blank=True, verbose_name="对象路径")
    local_path = models.CharField(max_length=1024, blank=True, verbose_name="本地路径")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="backup_runs",
        verbose_name="创建人",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    started_at = models.DateTimeField(null=True, blank=True, verbose_name="开始时间")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="结束时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "数据备份任务"
        verbose_name_plural = "数据备份任务"
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("plan_type", "status"),
                name="core_backup_plan_ty_764d98_idx",
            ),
            models.Index(
                fields=("target_type", "status"),
                name="core_backup_target__a2f1f3_idx",
            ),
            models.Index(
                fields=("trigger", "created_at"),
                name="core_backup_trigger_59a9e8_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("plan_type",),
                condition=models.Q(status__in=("queued", "running")),
                name="uniq_active_backup_run_per_plan",
            )
        ]

    def __str__(self):
        return f"{self.get_plan_type_display()} {self.status}"
