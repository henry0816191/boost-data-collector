from django.contrib import admin
from django.contrib.admin import ModelAdmin

from .models import MailingListMessage


@admin.register(MailingListMessage)
class MailingListMessageAdmin(ModelAdmin):
    list_display = (
        "id",
        "sender",
        "msg_id",
        "list_name",
        "subject",
        "sent_at",
        "created_at",
    )
    list_filter = ("list_name", "sent_at")
    search_fields = ("msg_id", "subject", "sender__display_name")
    raw_id_fields = ("sender",)
    date_hierarchy = "sent_at"
