"""
Read-only model mappings used by the dashboard app.

These map existing tables created/owned by other apps and are unmanaged.
"""

from django.db import models


class BoostExternalRepository(models.Model):
    githubrepository_ptr = models.OneToOneField(
        "github_activity_tracker.GitHubRepository",
        on_delete=models.DO_NOTHING,
        primary_key=True,
        db_column="githubrepository_ptr_id",
        related_name="dashboard_external_repo",
    )
    boost_version = models.CharField(max_length=64, db_index=True, blank=True)
    is_boost_embedded = models.BooleanField(default=False)
    is_boost_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "boost_usage_tracker_boostexternalrepository"
        managed = False


class BoostUsage(models.Model):
    repo = models.ForeignKey(
        BoostExternalRepository,
        on_delete=models.DO_NOTHING,
        db_column="repo_id",
        related_name="usages",
    )
    boost_header = models.ForeignKey(
        "boost_library_tracker.BoostFile",
        on_delete=models.DO_NOTHING,
        db_column="boost_header_id",
        related_name="dashboard_usages",
        null=True,
        blank=True,
    )
    file_path = models.ForeignKey(
        "github_activity_tracker.GitHubFile",
        on_delete=models.DO_NOTHING,
        db_column="file_path_id",
        related_name="dashboard_boost_usages",
    )
    last_commit_date = models.DateTimeField(null=True, blank=True, db_index=True)
    excepted_at = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "boost_usage_tracker_boostusage"
        managed = False
