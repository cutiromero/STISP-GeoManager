from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent", "0004_workflows")]

    operations = [
        migrations.AddField(
            model_name="agentrun",
            name="thinking_mode",
            field=models.CharField(default="fast", max_length=8),
        ),
    ]
