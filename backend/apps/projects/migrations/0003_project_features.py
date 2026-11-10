from django.db import migrations, models
import django.db.models.deletion


def seed_monitor(apps, schema_editor):
    alias = schema_editor.connection.alias
    feature_model = apps.get_model("projects", "ProjectFeature")
    setting_model = apps.get_model("projects", "ProjectFeatureSetting")
    project_model = apps.get_model("projects", "Project")
    feature, _ = feature_model.objects.using(alias).get_or_create(key="ecology_monitor")
    project = project_model.objects.using(alias).filter(code="05").first()
    if project is not None:
        setting_model.objects.using(alias).get_or_create(
            project_id=project.pk,
            feature_id=feature.pk,
            defaults={
                "enabled": True,
                "config": {
                    "title": "塔里木河流域胡杨林生态监测",
                    "source": "tarim_poplar_mock",
                    "initialView": {
                        "center": [84, 39.9],
                        "zoom": 2.05,
                        "regionZoom": 5.15,
                    },
                },
            },
        )


class Migration(migrations.Migration):
    dependencies = [("projects", "0002_public_project_name")]

    operations = [
        migrations.CreateModel(
            name="ProjectFeature",
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
                ("key", models.SlugField(max_length=80, unique=True)),
                ("globally_enabled", models.BooleanField(default=False)),
            ],
            options={"ordering": ("key",)},
        ),
        migrations.CreateModel(
            name="ProjectFeatureSetting",
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
                ("enabled", models.BooleanField(default=False)),
                ("config", models.JSONField(blank=True, null=True)),
                (
                    "feature",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="projects.projectfeature",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="feature_settings",
                        to="projects.project",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("project", "feature"), name="unique_project_feature"
                    )
                ]
            },
        ),
        migrations.RunPython(seed_monitor, migrations.RunPython.noop),
    ]
