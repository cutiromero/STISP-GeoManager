# Generated for data backup task history.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_add_ai_interpretation_permission"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="BackupRun",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "plan_type",
                    models.CharField(
                        choices=[("platform", "平台数据"), ("research", "科研数据")],
                        max_length=16,
                        verbose_name="备份类型",
                    ),
                ),
                (
                    "target_type",
                    models.CharField(
                        choices=[("local", "本地目录"), ("object_storage", "对象存储")],
                        max_length=32,
                        verbose_name="备份目标",
                    ),
                ),
                (
                    "trigger",
                    models.CharField(
                        choices=[("manual", "手动触发"), ("scheduled", "计划触发")],
                        max_length=16,
                        verbose_name="触发方式",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "等待中"),
                            ("running", "运行中"),
                            ("success", "成功"),
                            ("failed", "失败"),
                        ],
                        default="queued",
                        max_length=16,
                        verbose_name="任务状态",
                    ),
                ),
                (
                    "progress_percent",
                    models.PositiveSmallIntegerField(
                        default=0, verbose_name="进度百分比"
                    ),
                ),
                (
                    "messages",
                    models.JSONField(blank=True, default=list, verbose_name="任务消息"),
                ),
                (
                    "result",
                    models.JSONField(blank=True, null=True, verbose_name="任务结果"),
                ),
                (
                    "error_message",
                    models.TextField(blank=True, verbose_name="错误信息"),
                ),
                (
                    "archive_name",
                    models.CharField(blank=True, max_length=255, verbose_name="归档名"),
                ),
                (
                    "size_bytes",
                    models.PositiveBigIntegerField(default=0, verbose_name="归档大小"),
                ),
                (
                    "checksum_sha256",
                    models.CharField(
                        blank=True, max_length=64, verbose_name="SHA256 校验值"
                    ),
                ),
                (
                    "object_key",
                    models.CharField(
                        blank=True, max_length=1024, verbose_name="对象路径"
                    ),
                ),
                (
                    "local_path",
                    models.CharField(
                        blank=True, max_length=1024, verbose_name="本地路径"
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="创建时间"),
                ),
                (
                    "started_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="开始时间"
                    ),
                ),
                (
                    "finished_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="结束时间"
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, verbose_name="更新时间"),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="backup_runs",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="创建人",
                    ),
                ),
            ],
            options={
                "verbose_name": "数据备份任务",
                "verbose_name_plural": "数据备份任务",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="backuprun",
            index=models.Index(
                fields=["plan_type", "status"], name="core_backup_plan_ty_764d98_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="backuprun",
            index=models.Index(
                fields=["target_type", "status"], name="core_backup_target__a2f1f3_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="backuprun",
            index=models.Index(
                fields=["trigger", "created_at"], name="core_backup_trigger_59a9e8_idx"
            ),
        ),
    ]
