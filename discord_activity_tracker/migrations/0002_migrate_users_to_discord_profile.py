"""Data migration: copy DiscordUser → DiscordProfile, remap DiscordMessage.author_id."""

from django.db import migrations


def migrate_users_forward(apps, schema_editor):
    """Create DiscordProfile for each DiscordUser, remap DiscordMessage.author_id."""
    DiscordUser = apps.get_model("discord_activity_tracker", "DiscordUser")
    BaseProfile = apps.get_model("cppa_user_tracker", "BaseProfile")
    DiscordProfile = apps.get_model("cppa_user_tracker", "DiscordProfile")

    # Build mapping: old DiscordUser.pk → new DiscordProfile.pk
    pk_map = {}
    for du in DiscordUser.objects.all():
        # Create BaseProfile row first (multi-table inheritance)
        bp = BaseProfile.objects.create(type="discord")
        # Create DiscordProfile row
        DiscordProfile.objects.create(
            baseprofile_ptr_id=bp.pk,
            discord_user_id=du.user_id,
            username=du.username,
            display_name=du.display_name,
            avatar_url=du.avatar_url,
            is_bot=du.is_bot,
        )
        pk_map[du.pk] = bp.pk

    # Remap author_id in DiscordMessage using raw SQL for performance
    if pk_map:
        # Build CASE WHEN for bulk update
        case_parts = " ".join(
            f"WHEN {old_pk} THEN {new_pk}" for old_pk, new_pk in pk_map.items()
        )
        old_pks = ",".join(str(pk) for pk in pk_map.keys())
        sql = (
            f"UPDATE discord_activity_tracker_discordmessage "
            f"SET author_id = CASE author_id {case_parts} END "
            f"WHERE author_id IN ({old_pks})"
        )
        schema_editor.execute(sql)


def migrate_users_reverse(apps, schema_editor):
    """Reverse: this is a one-way migration. Raise error."""
    raise RuntimeError(
        "Cannot reverse DiscordUser → DiscordProfile migration. "
        "Restore from backup if needed."
    )


class Migration(migrations.Migration):

    dependencies = [
        ("cppa_user_tracker", "0003_discordprofile_alter_baseprofile_type"),
        ("discord_activity_tracker", "0001_initial"),
    ]

    operations = [
        # Step 1: Drop the old FK constraint so we can remap author_id values
        migrations.RunSQL(
            sql="ALTER TABLE discord_activity_tracker_discordmessage DROP CONSTRAINT IF EXISTS discord_activity_tra_author_id_1b8afaa8_fk_discord_a",
            reverse_sql="",  # handled by reverse data migration
        ),
        # Step 2: Data migration — create DiscordProfile, remap author_id
        migrations.RunPython(migrate_users_forward, migrate_users_reverse),
    ]
