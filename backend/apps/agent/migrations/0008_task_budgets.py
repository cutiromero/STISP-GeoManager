from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent", "0007_internet_enabled")]
    operations = [
        migrations.AddField(
            model_name="agentrun",
            name="budget_profile",
            field=models.CharField(max_length=16, blank=True, default=""),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="budget_snapshot",
            field=models.JSONField(default=dict),
        ),
    ]
