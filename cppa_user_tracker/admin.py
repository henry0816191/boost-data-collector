from django.contrib import admin
from django.contrib.admin import ModelAdmin

from .models import (
    BaseProfile,
    Email,
    GitHubAccount,
    Identity,
    MailingListProfile,
    SlackUser,
    TempProfileIdentityRelation,
    TmpIdentity,
    WG21PaperAuthorProfile,
)


@admin.register(Identity)
class IdentityAdmin(ModelAdmin):
    list_display = ("id", "display_name", "created_at", "updated_at")
    search_fields = ("display_name",)
    list_filter = ("created_at",)


@admin.register(TmpIdentity)
class TmpIdentityAdmin(ModelAdmin):
    list_display = ("id", "display_name", "created_at", "updated_at")
    search_fields = ("display_name",)
    list_filter = ("created_at",)


@admin.register(BaseProfile)
class BaseProfileAdmin(ModelAdmin):
    list_display = ("id", "identity", "type", "identity_id")
    list_filter = ("type",)
    raw_id_fields = ("identity",)


@admin.register(TempProfileIdentityRelation)
class TempProfileIdentityRelationAdmin(ModelAdmin):
    list_display = ("id", "base_profile", "target_identity", "created_at", "updated_at")
    list_filter = ("created_at",)
    raw_id_fields = ("base_profile", "target_identity")


@admin.register(Email)
class EmailAdmin(ModelAdmin):
    list_display = (
        "id",
        "base_profile",
        "email",
        "is_primary",
        "is_active",
        "created_at",
    )
    list_filter = ("is_primary", "is_active")
    search_fields = ("email",)
    raw_id_fields = ("base_profile",)


@admin.register(GitHubAccount)
class GitHubAccountAdmin(ModelAdmin):
    list_display = (
        "id",
        "identity",
        "github_account_id",
        "username",
        "display_name",
        "type",
        "updated_at",
    )
    list_filter = ("type",)
    search_fields = ("username", "display_name")
    raw_id_fields = ("identity",)


@admin.register(SlackUser)
class SlackUserAdmin(ModelAdmin):
    list_display = (
        "id",
        "identity",
        "slack_user_id",
        "username",
        "display_name",
        "updated_at",
    )
    search_fields = ("slack_user_id", "username", "display_name")
    raw_id_fields = ("identity",)


@admin.register(MailingListProfile)
class MailingListProfileAdmin(ModelAdmin):
    list_display = ("id", "identity", "display_name", "updated_at")
    search_fields = ("display_name",)
    raw_id_fields = ("identity",)


@admin.register(WG21PaperAuthorProfile)
class WG21PaperAuthorProfileAdmin(ModelAdmin):
    list_display = ("id", "identity", "display_name", "updated_at")
    search_fields = ("display_name",)
    raw_id_fields = ("identity",)
