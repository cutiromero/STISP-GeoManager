from django.db import migrations


def raise_legacy_step_limit(apps, schema_editor):
    AgentPolicy = apps.get_model("agent", "AgentPolicy")
    policy = AgentPolicy.objects.filter(pk=1).first()
    if not policy or not isinstance(policy.value, dict):
        return
    if policy.value.get("maxSteps") != 8:
        return
    value = dict(policy.value)
    value["maxSteps"] = 32
    policy.value = value
    policy.save(update_fields=["value", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("agent", "0002_default_permissions"),
    ]

    operations = [
        migrations.RunPython(
            raise_legacy_step_limit,
            migrations.RunPython.noop,
        ),
    ]
