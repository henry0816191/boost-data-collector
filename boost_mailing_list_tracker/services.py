"""
Service layer for boost_mailing_list_tracker.

All creates/updates/deletes for this app's models must go through functions here.
See docs/Contributing.md.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from .models import MailingListMessage, MailingListName

if TYPE_CHECKING:
    from datetime import datetime

    from cppa_user_tracker.models import MailingListProfile

logger = logging.getLogger(__name__)


# --- MailingListMessage ---
def get_or_create_mailing_list_message(
    sender: MailingListProfile,
    msg_id: str,
    parent_id: str = "",
    thread_id: str = "",
    subject: str = "",
    content: str = "",
    list_name: str = "",
    sent_at: Optional[datetime] = None,
) -> tuple[MailingListMessage, bool]:
    """Get or create a MailingListMessage by msg_id (unique).

    If the message already exists (same msg_id), no fields are updated.
    Returns (message, created).

    Raises:
        ValueError: If msg_id is empty or whitespace-only, or list_name is not a valid MailingListName.
    """
    if not (msg_id and msg_id.strip()):
        raise ValueError("msg_id must not be empty.")
    list_value = (list_name or "").strip()
    valid_values = [m.value for m in MailingListName]
    if list_value not in valid_values:
        raise ValueError(f"list_name must be one of {valid_values}, got {list_value!r}.")
    return MailingListMessage.objects.get_or_create(
        msg_id=msg_id.strip(),
        defaults={
            "sender": sender,
            "parent_id": parent_id,
            "thread_id": thread_id,
            "subject": subject,
            "content": content,
            "list_name": list_value,
            "sent_at": sent_at,
        },
    )


def delete_mailing_list_message(message: MailingListMessage) -> None:
    """Delete a MailingListMessage."""
    message.delete()
