import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_normalized_emails(apps, schema_editor):
    user_app_label, user_model_name = settings.AUTH_USER_MODEL.split(".")
    User = apps.get_model(user_app_label, user_model_name)
    UserProfile = apps.get_model("core", "UserProfile")
    claimed = set()
    for user in User.objects.order_by("id").iterator():
        email = str(user.email or "").strip().casefold()
        if email and user.email != email:
            user.email = email
            user.save(update_fields=["email"])
        profile, _ = UserProfile.objects.get_or_create(user_id=user.id)
        if email and email not in claimed:
            profile.normalized_email = email
            profile.save(update_fields=["normalized_email"])
            claimed.add(email)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0005_backuprun"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="normalized_email",
            field=models.EmailField(
                blank=True,
                max_length=254,
                null=True,
                unique=True,
                verbose_name="规范化邮箱",
            ),
        ),
        migrations.CreateModel(
            name="RoleApplication",
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
                    "requested_role",
                    models.CharField(
                        choices=[("research", "科研用户")],
                        default="research",
                        max_length=24,
                        verbose_name="申请角色",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "待审核"),
                            ("approved", "已通过"),
                            ("rejected", "已拒绝"),
                        ],
                        default="pending",
                        max_length=16,
                        verbose_name="申请状态",
                    ),
                ),
                ("reason", models.TextField(verbose_name="申请说明")),
                ("review_note", models.TextField(blank=True, verbose_name="审核说明")),
                (
                    "reviewed_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="审核时间"
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="申请时间"),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, verbose_name="更新时间"),
                ),
                (
                    "reviewer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reviewed_role_applications",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="审核人",
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="role_application",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="申请用户",
                    ),
                ),
            ],
            options={
                "verbose_name": "角色申请",
                "verbose_name_plural": "角色申请",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="roleapplication",
            index=models.Index(
                fields=["status", "created_at"],
                name="core_roleap_status_97a9dc_idx",
            ),
        ),
        migrations.RunPython(backfill_normalized_emails, migrations.RunPython.noop),
    ]
