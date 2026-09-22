import hashlib
import json

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def remove_legacy_topics_and_backfill_snapshots(apps, schema_editor):
    workspace_model = apps.get_model("catalog", "WorkspaceScene")
    composition_model = apps.get_model("catalog", "MapComposition")
    version_model = apps.get_model("catalog", "MapCompositionVersion")

    workspace_model.objects.filter(kind="topic").delete()

    for composition in composition_model.objects.select_related("project").iterator():
        if not composition.source_workspace_snapshot:
            composition.source_workspace_snapshot = composition.project.snapshot or {}
            composition.save(update_fields=["source_workspace_snapshot"])

    for version in version_model.objects.select_related(
        "composition__project"
    ).iterator():
        if not version.workspace_snapshot:
            version.workspace_snapshot = (
                version.composition.source_workspace_snapshot
                or version.composition.project.snapshot
                or {}
            )
        encoded = json.dumps(
            {
                "layout": version.layout_snapshot or {},
                "workspace": version.workspace_snapshot or {},
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        version.snapshot_checksum = hashlib.sha256(encoded).hexdigest()
        version.save(update_fields=["workspace_snapshot", "snapshot_checksum"])


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("catalog", "0007_map_composition"),
    ]

    operations = [
        migrations.RenameField(
            model_name="mapcomposition",
            old_name="access_groups",
            new_name="audience_groups",
        ),
        migrations.AlterField(
            model_name="mapcomposition",
            name="audience_groups",
            field=models.ManyToManyField(
                blank=True,
                related_name="map_compositions",
                to="auth.group",
                verbose_name="发布可见角色",
            ),
        ),
        migrations.AddField(
            model_name="mapcomposition",
            name="source_workspace_snapshot",
            field=models.JSONField(
                blank=True, default=dict, verbose_name="来源工程快照"
            ),
        ),
        migrations.AddField(
            model_name="mapcomposition",
            name="published_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="发布时间"),
        ),
        migrations.AddField(
            model_name="mapcomposition",
            name="published_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="published_map_compositions",
                to=settings.AUTH_USER_MODEL,
                verbose_name="发布人",
            ),
        ),
        migrations.AddField(
            model_name="mapcompositionversion",
            name="resource_manifest",
            field=models.JSONField(
                blank=True, default=list, verbose_name="资源引用清单"
            ),
        ),
        migrations.AddField(
            model_name="mapcompositionversion",
            name="snapshot_checksum",
            field=models.CharField(
                blank=True, max_length=64, verbose_name="快照校验值"
            ),
        ),
        migrations.AddField(
            model_name="mapcompositionversion",
            name="snapshot_schema_version",
            field=models.PositiveSmallIntegerField(
                default=1, verbose_name="快照结构版本"
            ),
        ),
        migrations.AddField(
            model_name="mapcompositionversion",
            name="workspace_snapshot",
            field=models.JSONField(blank=True, default=dict, verbose_name="工程快照"),
        ),
        migrations.AddField(
            model_name="mapcomposition",
            name="published_version",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="published_compositions",
                to="catalog.mapcompositionversion",
                verbose_name="正式发布版本",
            ),
        ),
        migrations.AlterField(
            model_name="workspacescene",
            name="kind",
            field=models.CharField(
                choices=[("project", "工程")], max_length=16, verbose_name="类型"
            ),
        ),
        migrations.AlterModelOptions(
            name="mapcomposition",
            options={
                "ordering": ("-updated_at", "id"),
                "permissions": [
                    ("export_mapcomposition", "导出专题图成果"),
                    ("publish_mapcomposition", "发布专题图成果"),
                    ("restore_mapcomposition", "还原专题图为工程"),
                ],
                "verbose_name": "专题出图稿",
                "verbose_name_plural": "专题出图稿",
            },
        ),
        migrations.RunPython(
            remove_legacy_topics_and_backfill_snapshots,
            migrations.RunPython.noop,
        ),
    ]
