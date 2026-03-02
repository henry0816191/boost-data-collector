from django.contrib import admin
from django.contrib.admin import ModelAdmin

from .models import BoostExternalRepository, BoostMissingHeaderTmp, BoostUsage


@admin.register(BoostExternalRepository)
class BoostExternalRepositoryAdmin(ModelAdmin):
    list_display = (
        "id",
        "owner_account",
        "repo_name",
        "stars",
        "boost_version",
        "is_boost_embedded",
        "is_boost_used",
        "created_at",
        "updated_at",
    )
    list_filter = ("is_boost_used", "is_boost_embedded", "created_at")
    search_fields = ("repo_name", "boost_version")
    raw_id_fields = ("owner_account",)


@admin.register(BoostUsage)
class BoostUsageAdmin(ModelAdmin):
    list_display = (
        "id",
        "repo",
        "boost_header",
        "file_path",
        "last_commit_date",
        "excepted_at",
        "created_at",
        "updated_at",
    )
    list_filter = ("excepted_at", "last_commit_date")
    search_fields = ("repo__repo_name",)
    raw_id_fields = ("repo", "boost_header", "file_path")


@admin.register(BoostMissingHeaderTmp)
class BoostMissingHeaderTmpAdmin(ModelAdmin):
    list_display = ("id", "usage", "header_name", "created_at")
    list_filter = ("created_at",)
    search_fields = ("header_name",)
    raw_id_fields = ("usage",)
