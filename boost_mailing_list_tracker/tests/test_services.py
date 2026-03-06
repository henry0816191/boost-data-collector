"""Tests for boost_mailing_list_tracker.services.

Covers edge cases and boundaries: empty/None inputs, max lengths,
invalid list_name, get vs create behavior, and delete behavior.
"""

from datetime import datetime, timezone

import pytest

from boost_mailing_list_tracker import services
from boost_mailing_list_tracker.models import MailingListMessage, MailingListName


# --- get_or_create_mailing_list_message ---


@pytest.mark.django_db
def test_get_or_create_mailing_list_message_creates_new(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """get_or_create_mailing_list_message creates new message and returns (message, True)."""
    msg, created = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<new-msg@example.com>",
        sent_at=sample_sent_at,
        subject="Hello",
        list_name=default_list_name,
    )
    assert created is True
    assert msg.sender_id == mailing_list_profile.pk
    assert msg.msg_id == "<new-msg@example.com>"
    assert msg.subject == "Hello"
    assert msg.list_name == default_list_name
    assert msg.sent_at == sample_sent_at


@pytest.mark.django_db
def test_get_or_create_mailing_list_message_gets_existing(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """get_or_create_mailing_list_message returns existing and (message, False)."""
    services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<existing@example.com>",
        sent_at=sample_sent_at,
        subject="Original",
        list_name=default_list_name,
    )
    msg2, created2 = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<existing@example.com>",
        sent_at=datetime(2024, 7, 1, tzinfo=timezone.utc),
        subject="Updated subject",
        list_name=default_list_name,
    )
    assert created2 is False
    assert msg2.subject == "Original"  # not updated


@pytest.mark.django_db
def test_get_or_create_mailing_list_message_empty_msg_id_raises(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """get_or_create_mailing_list_message raises ValueError for empty msg_id."""
    with pytest.raises(ValueError, match="msg_id must not be empty"):
        services.get_or_create_mailing_list_message(
            mailing_list_profile,
            msg_id="",
            sent_at=sample_sent_at,
            list_name=default_list_name,
        )
    with pytest.raises(ValueError, match="msg_id must not be empty"):
        services.get_or_create_mailing_list_message(
            mailing_list_profile,
            msg_id="   ",
            sent_at=sample_sent_at,
            list_name=default_list_name,
        )


@pytest.mark.django_db
def test_get_or_create_mailing_list_message_invalid_list_name_raises(
    mailing_list_profile,
    sample_sent_at,
):
    """get_or_create_mailing_list_message raises ValueError for invalid list_name."""
    with pytest.raises(ValueError, match="list_name must be one of"):
        services.get_or_create_mailing_list_message(
            mailing_list_profile,
            msg_id="<msg@example.com>",
            sent_at=sample_sent_at,
            list_name="invalid-list",
        )
    with pytest.raises(ValueError, match="list_name must be one of"):
        services.get_or_create_mailing_list_message(
            mailing_list_profile,
            msg_id="<msg2@example.com>",
            sent_at=sample_sent_at,
            list_name="",
        )


@pytest.mark.django_db
def test_get_or_create_mailing_list_message_strips_msg_id(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """get_or_create_mailing_list_message strips whitespace from msg_id."""
    msg, created = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="  <trimmed@example.com>  ",
        sent_at=sample_sent_at,
        list_name=default_list_name,
    )
    assert created is True
    assert msg.msg_id == "<trimmed@example.com>"


@pytest.mark.django_db
def test_get_or_create_mailing_list_message_all_list_names(
    mailing_list_profile,
    sample_sent_at,
):
    """get_or_create_mailing_list_message accepts all MailingListName values."""
    for i, list_value in enumerate(MailingListName):
        msg, created = services.get_or_create_mailing_list_message(
            mailing_list_profile,
            msg_id=f"<msg-{i}@example.com>",
            sent_at=sample_sent_at,
            list_name=list_value.value,
        )
        assert created is True
        assert msg.list_name == list_value.value


# --- delete_mailing_list_message ---


@pytest.mark.django_db
def test_delete_mailing_list_message_removes_from_db(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """delete_mailing_list_message deletes the message from database."""
    msg, _ = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<to-delete@example.com>",
        sent_at=sample_sent_at,
        list_name=default_list_name,
    )
    pk = msg.pk
    services.delete_mailing_list_message(msg)
    assert not MailingListMessage.objects.filter(pk=pk).exists()


@pytest.mark.django_db
def test_delete_mailing_list_message_returns_none(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """delete_mailing_list_message returns None."""
    msg, _ = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<return-none@example.com>",
        sent_at=sample_sent_at,
        list_name=default_list_name,
    )
    result = services.delete_mailing_list_message(msg)
    assert result is None


@pytest.mark.django_db
def test_delete_mailing_list_message_leaves_others(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """delete_mailing_list_message only removes the given message."""
    services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<keep@example.com>",
        sent_at=sample_sent_at,
        list_name=default_list_name,
    )
    msg2, _ = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<remove@example.com>",
        sent_at=sample_sent_at,
        list_name=default_list_name,
    )
    services.delete_mailing_list_message(msg2)
    assert MailingListMessage.objects.filter(msg_id="<keep@example.com>").exists()
    assert not MailingListMessage.objects.filter(msg_id="<remove@example.com>").exists()


# --- Edge cases: None / empty list_name ---


@pytest.mark.django_db
def test_get_or_create_mailing_list_message_none_list_name_raises(
    mailing_list_profile,
    sample_sent_at,
):
    """get_or_create_mailing_list_message raises ValueError for None list_name (invalid)."""
    with pytest.raises(ValueError, match="list_name must be one of"):
        services.get_or_create_mailing_list_message(
            mailing_list_profile,
            msg_id="<msg@example.com>",
            sent_at=sample_sent_at,
            list_name=None,  # type: ignore[arg-type]
        )


# --- Edge cases: max length and long content ---


@pytest.mark.django_db
def test_get_or_create_mailing_list_message_msg_id_at_max_length(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """get_or_create_mailing_list_message accepts msg_id of 255 chars (max_length)."""
    long_msg_id = "a" * 255
    msg, created = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id=long_msg_id,
        sent_at=sample_sent_at,
        list_name=default_list_name,
    )
    assert created is True
    assert len(msg.msg_id) == 255


@pytest.mark.django_db
def test_get_or_create_mailing_list_message_large_subject_and_content(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """get_or_create_mailing_list_message accepts subject 1024 and large content."""
    subject_1024 = "s" * 1024
    content_large = "c" * 10000
    msg, created = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<large@example.com>",
        sent_at=sample_sent_at,
        subject=subject_1024,
        content=content_large,
        list_name=default_list_name,
    )
    assert created is True
    assert len(msg.subject) == 1024
    assert len(msg.content) == 10000


# --- Boundary: get_or_create does not update existing ---


@pytest.mark.django_db
def test_get_or_create_mailing_list_message_does_not_update_any_field(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """get_or_create_mailing_list_message leaves all fields unchanged on existing msg."""
    services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<no-update@example.com>",
        sent_at=sample_sent_at,
        parent_id="old_parent",
        thread_id="old_thread",
        subject="Old subject",
        content="Old content",
        list_name=default_list_name,
    )
    msg2, created = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="  <no-update@example.com>  ",  # stripped to same
        sent_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        parent_id="new_parent",
        thread_id="new_thread",
        subject="New subject",
        content="New content",
        list_name=MailingListName.BOOST.value,
    )
    assert created is False
    assert msg2.parent_id == "old_parent"
    assert msg2.thread_id == "old_thread"
    assert msg2.subject == "Old subject"
    assert msg2.content == "Old content"
    assert msg2.list_name == default_list_name
