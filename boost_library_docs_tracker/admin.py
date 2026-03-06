from django.contrib import admin
from django.contrib.admin import ModelAdmin

from .models import BoostDocContent, BoostLibraryDocumentation


@admin.register(BoostDocContent)
class BoostDocContentAdmin(ModelAdmin):
    list_display = (
        "id",
        "url",
        "content_hash",
        "first_version",
        "last_version",
        "is_upserted",
        "scraped_at",
        "created_at",
    )
    search_fields = ("url", "content_hash")
    list_filter = ("is_upserted", "scraped_at")
    readonly_fields = ("created_at", "scraped_at")
    raw_id_fields = ("first_version", "last_version")


@admin.register(BoostLibraryDocumentation)
class BoostLibraryDocumentationAdmin(ModelAdmin):
    list_display = ("id", "boost_library_version", "boost_doc_content", "created_at")
    search_fields = ("boost_doc_content__url",)
    raw_id_fields = ("boost_library_version", "boost_doc_content")
    readonly_fields = ("created_at",)
