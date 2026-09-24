from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent", "0009_budget_database_defaults")]

    operations = [
        migrations.AddField(
            model_name="agentrun",
            name="reasoning_effort",
            field=models.CharField(max_length=8, blank=True, default="", db_default=""),
        ),
    ]
