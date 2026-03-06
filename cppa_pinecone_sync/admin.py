from django.contrib import admin
from django.contrib.admin import ModelAdmin

from .models import PineconeFailList, PineconeSyncStatus


@admin.register(PineconeFailList)
class PineconeFailListAdmin(ModelAdmin):
    list_display = ("id", "app_type", "failed_id", "created_at")
    list_filter = ("app_type", "created_at")
    search_fields = ("app_type", "failed_id")


@admin.register(PineconeSyncStatus)
class PineconeSyncStatusAdmin(ModelAdmin):
    list_display = ("id", "app_type", "final_sync_at", "created_at", "updated_at")
    list_filter = ("app_type",)
    search_fields = ("app_type",)
