"""
Models per docs/Schema.md section 5: Boost Mailing List Tracker.
References cppa_user_tracker.MailingListProfile (section 1) as sender.
"""

from django.db import models


class MailingListMessage(models.Model):
    """Mailing list message (sender -> MailingListProfile, msg_id, subject, content, list_name, sent_at)."""

    sender = models.ForeignKey(
        "cppa_user_tracker.MailingListProfile",
        on_delete=models.CASCADE,
        related_name="mailing_list_messages",
        db_column="sender_id",
    )
    msg_id = models.CharField(max_length=255, unique=True, db_index=True)
    parent_id = models.CharField(max_length=255, blank=True, db_index=True)
    thread_id = models.CharField(max_length=255, blank=True, db_index=True)
    subject = models.CharField(max_length=1024, blank=True)
    content = models.TextField(blank=True)
    list_name = models.CharField(max_length=255, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "boost_mailing_list_tracker_mailinglistmessage"
        ordering = ["-sent_at"]
        verbose_name = "Mailing list message"
        verbose_name_plural = "Mailing list messages"

    def __str__(self):
        return f"{self.list_name}: {self.subject[:60]}" if self.subject else self.msg_id
