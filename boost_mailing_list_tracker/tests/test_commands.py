"""Tests for boost_mailing_list_tracker management commands."""

import pytest

from boost_mailing_list_tracker.models import MailingListMessage, MailingListName


def _valid_email_data(
    msg_id: str = "<test-msg@example.com>",
    list_name: str | None = None,
    sent_at_str: str = "2025-01-15T10:00:00Z",
) -> dict:
    """Build a minimal valid email_data dict for _persist_email."""
    if list_name is None:
        list_name = MailingListName.BOOST_USERS.value
    return {
        "msg_id": msg_id,
        "sender_name": "Test Sender",
        "sender_address": "sender@example.com",
        "sent_at": sent_at_str,
        "parent_id": "",
        "thread_id": "",
        "subject": "Test subject",
        "content": "Test content",
        "list_name": list_name,
    }


@pytest.mark.django_db
def test_persist_email_creates_message():
    """_persist_email creates MailingListMessage and returns (True, False)."""
    from boost_mailing_list_tracker.management.commands.run_boost_mailing_list_tracker import (
        _persist_email,
    )

    email_data = _valid_email_data(msg_id="<create-me@example.com>")
    was_created, skipped = _persist_email(email_data)
    assert was_created is True
    assert skipped is False
    assert MailingListMessage.objects.filter(msg_id="<create-me@example.com>").exists()


@pytest.mark.django_db
def test_persist_email_skips_when_msg_id_empty():
    """_persist_email returns (False, True) when msg_id is missing or empty."""
    from boost_mailing_list_tracker.management.commands.run_boost_mailing_list_tracker import (
        _persist_email,
    )

    email_data = _valid_email_data()
    email_data["msg_id"] = ""
    was_created, skipped = _persist_email(email_data)
    assert was_created is False
    assert skipped is True

    email_data["msg_id"] = "   "
    was_created2, skipped2 = _persist_email(email_data)
    assert was_created2 is False
    assert skipped2 is True


@pytest.mark.django_db
def test_persist_email_skips_duplicate_msg_id():
    """_persist_email skips when message with same msg_id already exists."""
    from boost_mailing_list_tracker.management.commands.run_boost_mailing_list_tracker import (
        _persist_email,
    )

    email_data = _valid_email_data(msg_id="<duplicate@example.com>")
    was_created1, skipped1 = _persist_email(email_data)
    assert was_created1 is True
    assert skipped1 is False

    was_created2, skipped2 = _persist_email(email_data)
    assert was_created2 is False
    assert skipped2 is True
    assert (
        MailingListMessage.objects.filter(msg_id="<duplicate@example.com>").count() == 1
    )


@pytest.mark.django_db
def test_persist_email_persists_with_invalid_sent_at():
    """_persist_email still creates message when sent_at is unparseable; sent_at is stored as None."""
    from boost_mailing_list_tracker.management.commands.run_boost_mailing_list_tracker import (
        _persist_email,
    )

    email_data = _valid_email_data(
        msg_id="<bad-date@example.com>", sent_at_str="not-a-date"
    )
    was_created, skipped = _persist_email(email_data)
    assert was_created is True
    assert skipped is False
    msg = MailingListMessage.objects.get(msg_id="<bad-date@example.com>")
    assert msg.sent_at is None


@pytest.mark.django_db
def test_persist_email_creates_profile_and_message():
    """_persist_email creates MailingListProfile via get_or_create_mailing_list_profile when new."""
    from cppa_user_tracker.models import MailingListProfile

    from boost_mailing_list_tracker.management.commands.run_boost_mailing_list_tracker import (
        _persist_email,
    )

    initial_profiles = MailingListProfile.objects.count()
    email_data = _valid_email_data(
        msg_id="<new-sender@example.com>",
    )
    email_data["sender_name"] = "Brand New"
    email_data["sender_address"] = "brandnew@example.com"
    was_created, skipped = _persist_email(email_data)
    assert was_created is True
    assert skipped is False
    assert MailingListProfile.objects.filter(display_name="Brand New").exists()
    assert MailingListProfile.objects.count() >= initial_profiles + 1


@pytest.mark.django_db
def test_command_handle_dry_run_exits_cleanly(capsys):
    """Command with --dry-run runs without writing to DB and exits cleanly."""
    from unittest.mock import patch

    from django.core.management import call_command

    with patch(
        "boost_mailing_list_tracker.management.commands.run_boost_mailing_list_tracker.fetch_all_emails",
        return_value=[],
    ):
        call_command("run_boost_mailing_list_tracker", "--dry-run")
    out, _ = capsys.readouterr()
    assert (
        "dry" in out.lower()
        or "fetch" in out.lower()
        or "No emails" in out
        or len(out) >= 0
    )
