from django.db import migrations, models


def _normalize_name(value: str) -> str:
    value = (value or "").strip().lower()
    chars = []
    for ch in value:
        if ch.isalnum():
            chars.append(ch)
        else:
            chars.append("_")
    slug = "".join(chars).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "unknown"


def populate_external_id(apps, schema_editor):
    YoutubeSpeaker = apps.get_model("cppa_user_tracker", "YoutubeSpeaker")

    used = set(
        YoutubeSpeaker.objects.exclude(external_id__isnull=True)
        .exclude(external_id="")
        .values_list("external_id", flat=True)
    )

    for speaker in YoutubeSpeaker.objects.all().order_by("baseprofile_ptr_id"):
        if speaker.external_id:
            continue
        base = _normalize_name(speaker.display_name)
        candidate = f"legacy:{base}"
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
        migrations.AddField(
            model_name="youtubespeaker",
            name="external_id",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.RunPython(populate_external_id, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="youtubespeaker",
            name="external_id",
            field=models.CharField(max_length=255, unique=True),
        ),
    ]
