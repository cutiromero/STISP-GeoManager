from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent", "0006_attachments")]

    operations = [
        migrations.AddField(
            model_name="agentrun",
            name="internet_enabled",
            field=models.BooleanField(default=False),
        ),
    ]
