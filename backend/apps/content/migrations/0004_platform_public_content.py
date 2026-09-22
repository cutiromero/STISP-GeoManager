from django.db import migrations, models


def make_content_public(apps, schema_editor):
    # Historical managers permit a deliberate data migration across project scopes.
    alias = schema_editor.connection.alias
    articles = apps.get_model("content", "Article").objects.using(alias)
    assets = apps.get_model("content", "Asset").objects.using(alias)
    used = set(
        articles.filter(project_tag_id=1)
        .exclude(seed_key="")
        .values_list("seed_key", flat=True)
    )
    for article in articles.exclude(project_tag_id=1).order_by("id").iterator():
        key = article.seed_key
        if key and key in used:
            counter = 0
            while key in used:
                counter += 1
                key = f"migrated-{article.pk}-{counter}:{article.seed_key}"[:100]
        if key:
            used.add(key)
        articles.filter(pk=article.pk).update(project_tag_id=1, seed_key=key)
    # Files are addressed by their stored app-data-relative path; preserve it.
    assets.exclude(project_tag_id=1).update(project_tag_id=1)


class Migration(migrations.Migration):
    dependencies = [
        ("content", "0003_alter_article_owner"),
        ("projects", "0002_public_project_name"),
    ]
    operations = [
        migrations.RunPython(make_content_public, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="article",
            constraint=models.CheckConstraint(
                condition=models.Q(project_tag_id=1),
                name="content_article_public_project",
            ),
        ),
        migrations.AddConstraint(
            model_name="asset",
            constraint=models.CheckConstraint(
                condition=models.Q(project_tag_id=1),
                name="content_asset_public_project",
            ),
        ),
    ]
