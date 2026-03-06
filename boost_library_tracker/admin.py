from django.contrib import admin
from django.contrib.admin import ModelAdmin

from .models import (
    BoostDependency,
    BoostFile,
    BoostLibrary,
    BoostLibraryCategory,
    BoostLibraryCategoryRelationship,
    BoostLibraryRepository,
    BoostLibraryRoleRelationship,
    BoostLibraryVersion,
    BoostVersion,
    DependencyChangeLog,
)


@admin.register(BoostLibraryRepository)
class BoostLibraryRepositoryAdmin(ModelAdmin):
    """Admin for BoostLibraryRepository (Boost repos synced from GitHub)."""

    list_display = ("id", "owner_account", "repo_name", "created_at", "updated_at")
    list_filter = ("created_at",)
    search_fields = ("repo_name",)
    raw_id_fields = ("owner_account",)


@admin.register(BoostLibrary)
class BoostLibraryAdmin(ModelAdmin):
    """Admin for BoostLibrary (library within a Boost repo)."""

    list_display = ("id", "repo", "name")
    list_filter = ("repo",)
    search_fields = ("name",)
    raw_id_fields = ("repo",)


@admin.register(BoostFile)
class BoostFileAdmin(ModelAdmin):
    """Admin for BoostFile (links GitHubFile to BoostLibrary)."""

    list_display = ("github_file", "library")
    raw_id_fields = ("github_file", "library")


@admin.register(BoostVersion)
class BoostVersionAdmin(ModelAdmin):
    """Admin for BoostVersion (Boost release tag, e.g. boost-1.84.0)."""

    list_display = ("id", "version", "version_created_at")
    search_fields = ("version",)


@admin.register(BoostLibraryVersion)
class BoostLibraryVersionAdmin(ModelAdmin):
    """Admin for BoostLibraryVersion (library metadata for a given Boost version)."""

    list_display = ("id", "library", "version", "cpp_version", "updated_at")
    list_filter = ("version",)
    search_fields = ("library__name", "cpp_version")
    raw_id_fields = ("library", "version")


@admin.register(BoostDependency)
class BoostDependencyAdmin(ModelAdmin):
    """Admin for BoostDependency (client library depends on dep library for a version)."""

    list_display = ("id", "client_library", "version", "dep_library", "created_at")
    list_filter = ("version",)
    raw_id_fields = ("client_library", "version", "dep_library")


@admin.register(DependencyChangeLog)
class DependencyChangeLogAdmin(ModelAdmin):
    """Admin for DependencyChangeLog (dependency added/removed over time)."""

    list_display = ("id", "client_library", "dep_library", "is_add", "created_at")
    list_filter = ("is_add", "created_at")
    raw_id_fields = ("client_library", "dep_library")


@admin.register(BoostLibraryCategory)
class BoostLibraryCategoryAdmin(ModelAdmin):
    """Admin for BoostLibraryCategory (e.g. Math, Algorithms)."""

    list_display = ("id", "name", "created_at", "updated_at")
    search_fields = ("name",)


@admin.register(BoostLibraryRoleRelationship)
class BoostLibraryRoleRelationshipAdmin(ModelAdmin):
    """Admin for BoostLibraryRoleRelationship (author/maintainer of a library version)."""

    list_display = (
        "id",
        "library_version",
        "account",
        "is_maintainer",
        "is_author",
        "updated_at",
    )
    list_filter = ("is_maintainer", "is_author")
    raw_id_fields = ("library_version", "account")


@admin.register(BoostLibraryCategoryRelationship)
class BoostLibraryCategoryRelationshipAdmin(ModelAdmin):
    """Admin for BoostLibraryCategoryRelationship (library-category link)."""

    list_display = ("id", "library", "category", "created_at", "updated_at")
    raw_id_fields = ("library", "category")
