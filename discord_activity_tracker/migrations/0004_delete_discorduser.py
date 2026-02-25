from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("discord_activity_tracker", "0003_alter_discordmessage_author"),
    ]

    operations = [
        migrations.DeleteModel(
            name="DiscordUser",
        ),
    ]
