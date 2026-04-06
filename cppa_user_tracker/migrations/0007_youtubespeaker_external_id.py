import re

from django.db import migrations, models


def _slugify_speaker_name(name: str) -> str:
    """Match cppa_youtube_script_tracker.utils._slugify_speaker_name (no channel/video)."""
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "unknown"


def populate_external_id(apps, schema_editor):
    """Seed external_id using same format as build_speaker_external_id(..., "", "")."""
    YoutubeSpeaker = apps.get_model("cppa_user_tracker", "YoutubeSpeaker")

    used = set(
        YoutubeSpeaker.objects.exclude(external_id__isnull=True)
        .exclude(external_id="")
        .values_list("external_id", flat=True)
    )

    for speaker in YoutubeSpeaker.objects.all().order_by("baseprofile_ptr_id"):
        if speaker.external_id:
            continue
        slug = _slugify_speaker_name(speaker.display_name)
        candidate = f"youtube:name:{slug}"
        if candidate in used:
            candidate = f"{candidate}:{speaker.baseprofile_ptr_id}"
        speaker.external_id = candidate
        speaker.save(update_fields=["external_id"])
        used.add(candidate)


class Migration(migrations.Migration):

    dependencies = [
        ("cppa_user_tracker", "0006_alter_slackuser_slack_user_id"),
    ]

    operations = [
        # Defensive cleanup for previously failed local runs.
        migrations.RunSQL(
            sql=(
                "DROP INDEX IF EXISTS "
                "cppa_user_tracker_youtubespeaker_external_id_8b44bffb_like;"
                "DROP INDEX IF EXISTS "
                "cppa_user_tracker_youtubespeaker_external_id_8b44bffb;"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Add column if missing (no-op when 0005 already created it; required when
        # upgrading from pre-fix 0005 that did not include external_id).
        migrations.RunSQL(
            sql=(
                "ALTER TABLE cppa_user_tracker_youtubespeaker "
                "ADD COLUMN IF NOT EXISTS external_id VARCHAR(255) NULL;"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunPython(populate_external_id, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="youtubespeaker",
            name="external_id",
            field=models.CharField(max_length=255, unique=True),
        ),
    ]
