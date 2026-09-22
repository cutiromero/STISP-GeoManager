from django.db import migrations


SUPERADMIN_GROUP_NAME = "超级管理员"


def ensure_workspace_superadmin_visibility(apps, schema_editor):
    group_model = apps.get_model("auth", "Group")
    workspace_model = apps.get_model("catalog", "WorkspaceScene")
    superadmin_group, _ = group_model.objects.get_or_create(name=SUPERADMIN_GROUP_NAME)
    through_model = workspace_model.access_groups.through
    existing_workspace_ids = set(
        through_model.objects.filter(group_id=superadmin_group.id).values_list(
            "workspacescene_id", flat=True
        )
    )
    through_model.objects.bulk_create(
        [
            through_model(
                workspacescene_id=workspace_id,
                group_id=superadmin_group.id,
            )
            for workspace_id in workspace_model.objects.exclude(
                id__in=existing_workspace_ids
            ).values_list("id", flat=True)
        ],
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0005_vector_dataset_and_vector_domain_type"),
    ]

    operations = [
        migrations.RunPython(
            ensure_workspace_superadmin_visibility,
            migrations.RunPython.noop,
        ),
    ]
