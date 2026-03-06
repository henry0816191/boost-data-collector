"""
Models per docs/Schema.md section 4: Boost Usage Tracker.

Extends github_activity_tracker (GitHubRepository, GitHubFile) and references
boost_library_tracker.BoostFile for Boost header files.
"""

from django.db import models
from django.db.models import Q

from github_activity_tracker.models import GitHubRepository


class BoostExternalRepository(GitHubRepository):
    """Extends GitHubRepository for external C++ repos that may use Boost.

    Inherits all repository fields (owner_account, repo_name, stars, forks,
    description, repo_pushed_at, repo_created_at, repo_updated_at) from
    GitHubRepository via multi-table inheritance.

    Additional fields:
      - boost_version: detected Boost version string (e.g. "1.84.0").
      - is_boost_embedded: True when the repo vendors a copy of Boost source.
      - is_boost_used: True when at least one ``#include <boost/…>`` was found.
    """

    boost_version = models.CharField(max_length=64, db_index=True, blank=True)
    is_boost_embedded = models.BooleanField(default=False)
    is_boost_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "boost_usage_tracker_boostexternalrepository"
        ordering = ["repo_name"]
        verbose_name = "Boost External Repository"
        verbose_name_plural = "Boost External Repositories"


class BoostUsage(models.Model):
    """Tracks which external repositories use which Boost headers in which files.

    Each row links:
      - repo → BoostExternalRepository (the external project).
      - boost_header → BoostFile (the Boost header file, e.g. ``boost/asio.hpp``).
      - file_path → GitHubFile (the source file in the external repo that
        contains the ``#include``).

    ``excepted_at`` is set when a previously-detected usage is no longer found
    (the include was removed or the file was deleted).
    """

    repo = models.ForeignKey(
        BoostExternalRepository,
        on_delete=models.CASCADE,
        related_name="boost_usages",
        db_column="repo_id",
    )
    boost_header = models.ForeignKey(
        "boost_library_tracker.BoostFile",
        on_delete=models.CASCADE,
        related_name="external_usages",
        db_column="boost_header_id",
        null=True,
        blank=True,
    )
    file_path = models.ForeignKey(
        "github_activity_tracker.GitHubFile",
        on_delete=models.CASCADE,
        related_name="boost_usages",
        db_column="file_path_id",
    )
    last_commit_date = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )
    excepted_at = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "boost_usage_tracker_boostusage"
        ordering = ["repo", "boost_header", "file_path"]
        verbose_name = "Boost Usage"
        verbose_name_plural = "Boost Usages"
        constraints = [
            models.UniqueConstraint(
                fields=["repo", "boost_header", "file_path"],
                name="boost_usage_tracker_usage_uniq",
            ),
            models.UniqueConstraint(
                fields=["repo", "file_path"],
                condition=Q(boost_header__isnull=True),
                name="boost_usage_tracker_usage_missing_header_uniq",
            ),
        ]


class BoostMissingHeaderTmp(models.Model):
    """Temporary record when a Boost include path is not yet in BoostFile/GitHubFile.

    usage_id references BoostUsage.id. Used to save usage history until the
    header is added to the catalog, then can be backfilled and removed.
    """

    usage = models.ForeignKey(
        BoostUsage,
        on_delete=models.CASCADE,
        related_name="missing_header_tmp",
        db_column="usage_id",
    )
    header_name = models.CharField(max_length=512, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "boost_usage_tracker_boostmissingheadertmp"
        ordering = ["usage", "header_name"]
        verbose_name = "Boost Missing Header Tmp"
        verbose_name_plural = "Boost Missing Header Tmp"
        constraints = [
            models.UniqueConstraint(
                fields=["usage", "header_name"],
                name="boost_usage_tracker_missing_header_tmp_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["usage"], name="boost_missing_tmp_usage_id"),
        ]
