import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent", "0019_workflow_upload")]

    operations = [
        migrations.AlterField(
            model_name="workflowupload",
            name="resource",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="catalog.dataresource",
            ),
        ),
        migrations.AddField(
            model_name="workflowupload",
            name="source",
            field=models.CharField(default="upload", max_length=16),
        ),
        migrations.AddConstraint(
            model_name="workflowupload",
            constraint=models.UniqueConstraint(
                fields=("project_tag", "owner", "batch_id", "resource"),
                name="agent_workflow_upload_batch_resource",
            ),
        ),
        migrations.AddConstraint(
            model_name="workflowupload",
            constraint=models.CheckConstraint(
                condition=models.Q(source__in=("upload", "catalog")),
                name="agent_workflow_upload_source_valid",
            ),
        ),
    ]
