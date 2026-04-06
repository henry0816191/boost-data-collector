from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("cppa_user_tracker", "0005_youtubespeaker_alter_baseprofile_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="YouTubeChannel",
            fields=[
                (
                    "channel_id",
                    models.CharField(max_length=64, primary_key=True, serialize=False),
                ),
                ("channel_title", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "YouTube channel",
                "verbose_name_plural": "YouTube channels",
                "ordering": ["channel_title"],
            },
        ),
        migrations.CreateModel(
            name="CppaTags",
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
                ("tag_name", models.CharField(db_index=True, max_length=128, unique=True)),
            ],
            options={
                "verbose_name": "CPPA tag",
                "verbose_name_plural": "CPPA tags",
                "ordering": ["tag_name"],
            },
        ),
        migrations.CreateModel(
            name="YouTubeVideo",
            fields=[
                (
                    "video_id",
                    models.CharField(max_length=32, primary_key=True, serialize=False),
                ),
                (
                    "channel",
                    models.ForeignKey(
                        blank=True,
                        db_column="channel_id",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="videos",
                        to="cppa_youtube_script_tracker.youtubechannel",
                    ),
                ),
                ("title", models.CharField(blank=True, max_length=512)),
                ("description", models.TextField(blank=True)),
                ("published_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("duration_seconds", models.IntegerField(default=0)),
                ("view_count", models.IntegerField(blank=True, null=True)),
                ("like_count", models.IntegerField(blank=True, null=True)),
                ("comment_count", models.IntegerField(blank=True, null=True)),
                ("search_term", models.CharField(blank=True, max_length=255)),
                ("has_transcript", models.BooleanField(default=False)),
                ("transcript_path", models.CharField(blank=True, max_length=1024)),
                ("scraped_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "YouTube video",
                "verbose_name_plural": "YouTube videos",
                "ordering": ["-published_at"],
            },
        ),
        migrations.CreateModel(
            name="YouTubeVideoSpeaker",
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
                (
                    "video",
                    models.ForeignKey(
                        db_column="video_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="video_speakers",
                        to="cppa_youtube_script_tracker.youtubevideo",
                    ),
                ),
                (
                    "speaker",
                    models.ForeignKey(
                        db_column="speaker_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="video_appearances",
                        to="cppa_user_tracker.youtubespeaker",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "YouTube video speaker",
                "verbose_name_plural": "YouTube video speakers",
                "ordering": ["video", "speaker"],
            },
        ),
        migrations.AddConstraint(
            model_name="youtubevideospeaker",
            constraint=models.UniqueConstraint(
                fields=["video", "speaker"], name="unique_video_speaker"
            ),
        ),
        migrations.CreateModel(
            name="YouTubeVideoTags",
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
                (
                    "youtube_video",
                    models.ForeignKey(
                        db_column="youtube_video_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="video_tags",
                        to="cppa_youtube_script_tracker.youtubevideo",
                    ),
                ),
                (
                    "cppa_tag",
                    models.ForeignKey(
                        db_column="cppa_tag_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tagged_videos",
                        to="cppa_youtube_script_tracker.cppatags",
                    ),
                ),
            ],
            options={
                "verbose_name": "YouTube video tag",
                "verbose_name_plural": "YouTube video tags",
                "ordering": ["youtube_video", "cppa_tag"],
            },
        ),
        migrations.AddConstraint(
            model_name="youtubevideotags",
            constraint=models.UniqueConstraint(
                fields=["youtube_video", "cppa_tag"], name="unique_video_tag"
            ),
        ),
    ]
