# Generated manually for clang_github_tracker models

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ClangGithubCommit",
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
                ("sha", models.CharField(max_length=40, unique=True)),
                (
                    "github_committed_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "clang_github_tracker_commit",
            },
        ),
        migrations.CreateModel(
            name="ClangGithubIssueItem",
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
                ("number", models.PositiveIntegerField(unique=True)),
                ("is_pull_request", models.BooleanField(default=False)),
                (
                    "github_created_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "github_updated_at",
                    models.DateTimeField(
                        blank=True,
                        db_index=True,
                        help_text="GitHub API updated_at; drives fetch watermarks.",
                        null=True,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        db_index=True,
                        help_text="Last DB save; drives Pinecone incrementality vs final_sync_at.",
                    ),
                ),
            ],
            options={
                "db_table": "clang_github_tracker_issue_item",
            },
        ),
    ]
