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
    list_display = ("id", "owner_account", "repo_name", "created_at", "updated_at")
    list_filter = ("created_at",)
    search_fields = ("repo_name",)
    raw_id_fields = ("owner_account",)


@admin.register(BoostLibrary)
class BoostLibraryAdmin(ModelAdmin):
    list_display = ("id", "repo", "name")
    list_filter = ("repo",)
    search_fields = ("name",)
    raw_id_fields = ("repo",)


@admin.register(BoostFile)
class BoostFileAdmin(ModelAdmin):
    list_display = ("github_file", "library")
    raw_id_fields = ("github_file", "library")


@admin.register(BoostVersion)
class BoostVersionAdmin(ModelAdmin):
    list_display = ("id", "version", "version_created_at")
    search_fields = ("version",)


@admin.register(BoostLibraryVersion)
class BoostLibraryVersionAdmin(ModelAdmin):
    list_display = ("id", "library", "version", "cpp_version", "updated_at")
    list_filter = ("version",)
    search_fields = ("library__name", "cpp_version")
    raw_id_fields = ("library", "version")


@admin.register(BoostDependency)
class BoostDependencyAdmin(ModelAdmin):
    list_display = ("id", "client_library", "version", "dep_library", "created_at")
    list_filter = ("version",)
    raw_id_fields = ("client_library", "version", "dep_library")


@admin.register(DependencyChangeLog)
class DependencyChangeLogAdmin(ModelAdmin):
    list_display = ("id", "client_library", "dep_library", "is_add", "created_at")
    list_filter = ("is_add", "created_at")
    raw_id_fields = ("client_library", "dep_library")


@admin.register(BoostLibraryCategory)
class BoostLibraryCategoryAdmin(ModelAdmin):
    list_display = ("id", "name", "created_at", "updated_at")
    search_fields = ("name",)


@admin.register(BoostLibraryRoleRelationship)
class BoostLibraryRoleRelationshipAdmin(ModelAdmin):
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
    list_display = ("id", "library", "category", "created_at", "updated_at")
    raw_id_fields = ("library", "category")
