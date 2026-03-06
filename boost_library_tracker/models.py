"""
Models per docs/Schema.md section 3: Boost Library Tracker.
Extends github_activity_tracker (GitHubRepository, GitHubFile) and references
cppa_user_tracker.GitHubAccount.
"""

from django.db import models

from github_activity_tracker.models import GitHubRepository


# --- Part 1: Boost Library, Headers, and Dependencies ---


class BoostLibraryRepository(GitHubRepository):
    """Extends GitHubRepository with boost-library-specific fields (multi-table inheritance)."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "boost_library_tracker_boostlibraryrepository"
        ordering = ["repo_name"]


class BoostLibrary(models.Model):
    """Boost library within a BoostLibraryRepository."""

    repo = models.ForeignKey(
        BoostLibraryRepository,
        on_delete=models.CASCADE,
        related_name="libraries",
        db_column="repo_id",
    )
    name = models.CharField(max_length=255, db_index=True)

    class Meta:
        db_table = "boost_library_tracker_boostlibrary"
        ordering = ["repo", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["repo", "name"],
                name="boost_library_tracker_repo_name_uniq",
            )
        ]


class BoostFile(models.Model):
    """Extends GitHubFile with library association (1:1 to GitHubFile)."""

    github_file = models.OneToOneField(
        "github_activity_tracker.GitHubFile",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="boost_file",
        db_column="github_file_id",
    )
    library = models.ForeignKey(
        BoostLibrary,
        on_delete=models.CASCADE,
        related_name="files",
        db_column="library_id",
    )

    class Meta:
        db_table = "boost_library_tracker_boostfile"


class BoostVersion(models.Model):
    """Boost release version (e.g. 1.81.0)."""

    version = models.CharField(max_length=64, unique=True, db_index=True)
    version_created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "boost_library_tracker_boostversion"
        ordering = ["-version_created_at", "version"]


class BoostLibraryVersion(models.Model):
    """Library version for a given Boost release."""

    library = models.ForeignKey(
        BoostLibrary,
        on_delete=models.CASCADE,
        related_name="library_versions",
        db_column="library_id",
    )
    version = models.ForeignKey(
        BoostVersion,
        on_delete=models.CASCADE,
        related_name="library_versions",
        db_column="version_id",
    )
    cpp_version = models.CharField(max_length=64, blank=True)
    description = models.TextField(blank=True)
    key = models.CharField(max_length=255, blank=True, db_index=True)
    documentation = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "boost_library_tracker_boostlibraryversion"
        ordering = ["library", "version"]
        constraints = [
            models.UniqueConstraint(
                fields=["library", "version"],
                name="boost_library_tracker_lib_version_uniq",
            )
        ]


class BoostDependency(models.Model):
    """Dependency: client_library depends on dep_library for a given Boost version."""

    client_library = models.ForeignKey(
        BoostLibrary,
        on_delete=models.CASCADE,
        related_name="dependencies_as_client",
        db_column="client_library_id",
    )
    version = models.ForeignKey(
        BoostVersion,
        on_delete=models.CASCADE,
        related_name="dependencies",
        db_column="version_id",
    )
    dep_library = models.ForeignKey(
        BoostLibrary,
        on_delete=models.CASCADE,
        related_name="dependencies_as_dep",
        db_column="dep_library_id",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "boost_library_tracker_boostdependency"
        ordering = ["client_library", "version", "dep_library"]
        constraints = [
            models.UniqueConstraint(
                fields=["client_library", "version", "dep_library"],
                name="boost_library_tracker_dep_uniq",
            )
        ]


class DependencyChangeLog(models.Model):
    """Log of dependency add/remove for a client/dep library pair."""

    client_library = models.ForeignKey(
        BoostLibrary,
        on_delete=models.CASCADE,
        related_name="dependency_changelog_as_client",
        db_column="client_library_id",
    )
    dep_library = models.ForeignKey(
        BoostLibrary,
        on_delete=models.CASCADE,
        related_name="dependency_changelog_as_dep",
        db_column="dep_library_id",
    )
    is_add = models.BooleanField()
    created_at = models.DateField(db_index=True)

    class Meta:
        db_table = "boost_library_tracker_dependencychangelog"
        ordering = ["-created_at", "client_library", "dep_library"]
        constraints = [
            models.UniqueConstraint(
                fields=["client_library", "dep_library", "created_at"],
                name="boost_library_tracker_changelog_uniq",
            )
        ]


# --- Part 2: Maintainers, Authors, and Categories ---


class BoostLibraryCategory(models.Model):
    """Category label for libraries (e.g. Math, Container)."""

    name = models.CharField(max_length=255, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "boost_library_tracker_boostlibrarycategory"
        ordering = ["name"]
        verbose_name_plural = "Boost library categories"


class BoostLibraryRoleRelationship(models.Model):
    """Maintainer/author of a library version (links GitHubAccount to BoostLibraryVersion)."""

    library_version = models.ForeignKey(
        BoostLibraryVersion,
        on_delete=models.CASCADE,
        related_name="role_relationships",
        db_column="library_version_id",
    )
    account = models.ForeignKey(
        "cppa_user_tracker.GitHubAccount",
        on_delete=models.CASCADE,
        related_name="boost_library_roles",
        db_column="account_id",
    )
    is_maintainer = models.BooleanField(default=False)
    is_author = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "boost_library_tracker_boostlibraryrolerelationship"
        ordering = ["library_version", "account"]
        constraints = [
            models.UniqueConstraint(
                fields=["library_version", "account"],
                name="boost_library_tracker_role_uniq",
            )
        ]


class BoostLibraryCategoryRelationship(models.Model):
    """Library–category link."""

    library = models.ForeignKey(
        BoostLibrary,
        on_delete=models.CASCADE,
        related_name="category_relationships",
        db_column="library_id",
    )
    category = models.ForeignKey(
        BoostLibraryCategory,
        on_delete=models.CASCADE,
        related_name="library_relationships",
        db_column="category_id",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "boost_library_tracker_boostlibrarycategoryrelationship"
        ordering = ["library", "category"]
        constraints = [
            models.UniqueConstraint(
                fields=["library", "category"],
                name="boost_library_tracker_lib_cat_uniq",
            )
        ]
