from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):
    dependencies = [("agent", "0005_thinking_mode")]

    operations = [
        migrations.CreateModel(
            name="AgentAttachment",
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
                ("name", models.CharField(max_length=255)),
                ("path", models.CharField(max_length=500)),
                ("mime_type", models.CharField(max_length=120)),
                (
                    "kind",
                    models.CharField(
                        choices=[("document", "文档"), ("image", "图片")],
                        max_length=16,
                    ),
                ),
                ("size_bytes", models.PositiveBigIntegerField(default=0)),
                ("checksum", models.CharField(max_length=64)),
                ("extracted_text", models.TextField(blank=True)),
                ("extraction_status", models.CharField(default="ready", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "conversation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attachments",
                        to="agent.conversation",
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "project_tag",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        default=1,
                        related_name="+",
                        to="projects.project",
                        verbose_name="项目标签",
                    ),
                ),
            ],
            options={"ordering": ("created_at", "id")},
        ),
        migrations.AddField(
            model_name="agentrun",
            name="attachment_ids",
            field=models.JSONField(default=list),
        ),
        migrations.AddConstraint(
            model_name="agentattachment",
            constraint=models.UniqueConstraint(
                fields=("conversation", "checksum"),
                name="agent_attachment_conversation_checksum",
            ),
        ),
    ]
