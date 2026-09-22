from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


AUTH_EVENT_CODES = (
    ("认证授权", "用户登录", "success", "auth.login.success"),
    ("认证授权", "用户登录", "failed", "auth.login.failed"),
    ("认证授权", "游客登录", "success", "auth.guest_login.success"),
    ("认证授权", "用户注册", "success", "auth.register_login.success"),
)


def populate_event_codes_and_activity(apps, schema_editor):
    OperationLog = apps.get_model("audit", "OperationLog")
    UserActivityHour = apps.get_model("audit", "UserActivityHour")

    for module, action, status, event_code in AUTH_EVENT_CODES:
        OperationLog.objects.filter(
            module=module,
            action=action,
            status=status,
        ).update(event_code=event_code)

    pending = []
    rows = OperationLog.objects.filter(
        status="success",
        user_id__isnull=False,
    ).values_list("user_id", "created_at")
    for user_id, created_at in rows.iterator(chunk_size=2000):
        bucket_start = timezone.localtime(created_at).replace(
            minute=0,
            second=0,
            microsecond=0,
        )
        pending.append(UserActivityHour(user_id=user_id, bucket_start=bucket_start))
        if len(pending) >= 2000:
            UserActivityHour.objects.bulk_create(pending, ignore_conflicts=True)
            pending.clear()
    if pending:
        UserActivityHour.objects.bulk_create(pending, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="operationlog",
            name="event_code",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=64,
                verbose_name="稳定事件编码",
            ),
        ),
        migrations.CreateModel(
            name="UserActivityHour",
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
                ("bucket_start", models.DateTimeField(verbose_name="小时起始时间")),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="记录时间"),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="activity_hours",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="活跃用户",
                    ),
                ),
            ],
            options={
                "verbose_name": "用户小时活跃记录",
                "verbose_name_plural": "用户小时活跃记录",
                "ordering": ("-bucket_start",),
                "indexes": [
                    models.Index(
                        fields=["bucket_start"],
                        name="audit_usera_bucket__6077f6_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "bucket_start"),
                        name="audit_activity_user_hour_unique",
                    )
                ],
            },
        ),
        migrations.RunPython(
            populate_event_codes_and_activity,
            migrations.RunPython.noop,
        ),
    ]
