"""Remove two known course-source suffixes from current science figure captions.

Article source notes and bodies remain intact. Archived content, replacement
images, and captions without the exact known suffix are deliberately preserved.
"""

import re

from django.db import migrations
from django.db.models import F
from django.utils import timezone


TARGETS = (
    (
        "science-20260929-07",
        "396528333558860571cec3d943163e77295d3c6687182ea55501fe93d6f6c776",
        21,
    ),
    (
        "science-20260929-08",
        "7e8186086313d666220186bcc3a8772f594afff60f1b7f790d5d5371e8ef2673",
        3,
    ),
)


def trim_caption_provenance(apps, schema_editor):
    alias = schema_editor.connection.alias
    articles = apps.get_model("content", "Article").objects.using(alias)
    assets = apps.get_model("content", "Asset").objects.using(alias)
    for seed_key, checksum, page in TARGETS:
        suffix = re.compile(rf"图源：课件第\s*8\s*讲，\s*第\s*{page}\s*页。\s*$")
        for article in articles.filter(
            project_tag_id=1, kind="knowledge", status="published", seed_key=seed_key
        ):
            changed = False
            for asset in assets.filter(
                article_id=article.pk,
                project_tag_id=1,
                checksum=checksum,
                mime_type__startswith="image/",
                expires_at__isnull=True,
                pending_owner_id__isnull=True,
            ):
                match = suffix.search(asset.caption)
                if match is None:
                    continue
                caption = asset.caption[: match.start()].rstrip()
                if not caption:
                    continue
                # Match the read value again so a concurrent editor is never overwritten.
                changed = (
                    bool(
                        assets.filter(pk=asset.pk, caption=asset.caption).update(
                            caption=caption
                        )
                    )
                    or changed
                )
            if changed:
                articles.filter(pk=article.pk).update(
                    revision=F("revision") + 1, updated_at=timezone.now()
                )


class Migration(migrations.Migration):
    dependencies = [("content", "0006_refresh_conference_news")]
    operations = [
        migrations.RunPython(trim_caption_provenance, migrations.RunPython.noop)
    ]
