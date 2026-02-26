from django.contrib import admin
from django.contrib.admin import ModelAdmin

from .models import PineconeFailList, PineconeSyncStatus


@admin.register(PineconeFailList)
class PineconeFailListAdmin(ModelAdmin):
    list_display = ("id", "app_id", "failed_id", "created_at")
    list_filter = ("app_id", "created_at")
    search_fields = ("failed_id",)


@admin.register(PineconeSyncStatus)
class PineconeSyncStatusAdmin(ModelAdmin):
    list_display = ("id", "app_id", "final_sync_at", "created_at", "updated_at")
    list_filter = ("app_id",)
    search_fields = ("app_id",)
