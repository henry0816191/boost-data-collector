from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("cppa_user_tracker", "0004_alter_slackuser_slack_user_id_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="YoutubeSpeaker",
            fields=[
                (
                    "baseprofile_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="cppa_user_tracker.baseprofile",
                    ),
                ),
                (
                    "external_id",
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                ("display_name", models.CharField(db_index=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            bases=("cppa_user_tracker.baseprofile",),
        ),
        migrations.AlterField(
            model_name="baseprofile",
            name="type",
            field=models.CharField(
                choices=[
                    ("github", "GitHub"),
                    ("slack", "Slack"),
                    ("mailing_list", "Mailing list"),
                    ("wg21", "WG21"),
                    ("discord", "Discord"),
                    ("youtube", "YouTube"),
                ],
                db_index=True,
                max_length=20,
            ),
        ),
    ]
