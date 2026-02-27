"""Tests for boost_mailing_list_tracker models.

Covers edge cases and boundaries: empty inputs, max lengths, invalid data,
and critical model behavior (constraints, Meta, __str__, relations).
"""

import pytest
from django.db import IntegrityError
from django.core.exceptions import ValidationError
from model_bakery import baker

from boost_mailing_list_tracker.models import MailingListMessage, MailingListName


# --- MailingListName ---


def test_mailing_list_name_choices():
    """MailingListName has expected list choices."""
    assert MailingListName.BOOST_ANNOUNCE.value == "boost-announce@lists.boost.org"
    assert MailingListName.BOOST_USERS.value == "boost-users@lists.boost.org"
    assert MailingListName.BOOST.value == "boost@lists.boost.org"
    assert len(MailingListName) == 3


def test_mailing_list_name_choices_structure():
    """MailingListName.choices returns list of (value, label) for form/validation."""
    choices = MailingListName.choices
    assert len(choices) == 3
    values = [c[0] for c in choices]
    labels = [c[1] for c in choices]
    assert "boost@lists.boost.org" in values
    assert "Boost Announce" in labels
    assert "Boost Users" in labels
    assert "Boost" in labels


def test_mailing_list_name_labels():
    """MailingListName labels are human-readable."""
    assert MailingListName.BOOST_ANNOUNCE.label == "Boost Announce"
    assert MailingListName.BOOST_USERS.label == "Boost Users"
    assert MailingListName.BOOST.label == "Boost"


# --- MailingListMessage ---


@pytest.mark.django_db
def test_mailing_list_message_links_sender(
    mailing_list_profile, default_list_name, sample_sent_at
):
    """MailingListMessage is linked to MailingListProfile as sender."""
    from boost_mailing_list_tracker import services

    msg, _ = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<msg-001@example.com>",
        sent_at=sample_sent_at,
        list_name=default_list_name,
    )
    assert msg.sender_id == mailing_list_profile.pk
    assert msg.sender == mailing_list_profile


@pytest.mark.django_db
def test_mailing_list_message_stores_msg_id_and_list_name(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """MailingListMessage stores msg_id and list_name."""
    from boost_mailing_list_tracker import services

    msg, _ = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<unique-msg@lists.boost.org>",
        sent_at=sample_sent_at,
        list_name=default_list_name,
    )
    assert msg.msg_id == "<unique-msg@lists.boost.org>"
    assert msg.list_name == default_list_name


@pytest.mark.django_db
def test_mailing_list_message_stores_optional_fields(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """MailingListMessage stores parent_id, thread_id, subject, content."""
    from boost_mailing_list_tracker import services

    msg, _ = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<with-fields@example.com>",
        sent_at=sample_sent_at,
        parent_id="<parent@example.com>",
        thread_id="thread-1",
        subject="Test subject",
        content="Body text",
        list_name=default_list_name,
    )
    assert msg.parent_id == "<parent@example.com>"
    assert msg.thread_id == "thread-1"
    assert msg.subject == "Test subject"
    assert msg.content == "Body text"


@pytest.mark.django_db
def test_mailing_list_message_has_created_at(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """MailingListMessage has created_at."""
    from boost_mailing_list_tracker import services

    msg, _ = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<created-at@example.com>",
        sent_at=sample_sent_at,
        list_name=default_list_name,
    )
    assert msg.created_at is not None


@pytest.mark.django_db
def test_mailing_list_message_ordering():
    """MailingListMessage Meta ordering is -sent_at."""
    assert MailingListMessage._meta.ordering == ["-sent_at"]


@pytest.mark.django_db
def test_mailing_list_message_str_with_subject(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """MailingListMessage __str__ uses subject (truncated) when present."""
    from boost_mailing_list_tracker import services

    msg, _ = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<str-subject@example.com>",
        sent_at=sample_sent_at,
        subject="A short subject",
        list_name=default_list_name,
    )
    assert "A short subject" in str(msg)
    assert default_list_name in str(msg)


@pytest.mark.django_db
def test_mailing_list_message_str_fallback_to_msg_id(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """MailingListMessage __str__ uses msg_id when subject empty."""
    from boost_mailing_list_tracker import services

    msg, _ = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<no-subject@example.com>",
        sent_at=sample_sent_at,
        subject="",
        list_name=default_list_name,
    )
    assert "<no-subject@example.com>" in str(msg)


@pytest.mark.django_db
def test_mailing_list_message_msg_id_unique(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """MailingListMessage msg_id is unique."""
    from boost_mailing_list_tracker import services

    services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<duplicate@example.com>",
        sent_at=sample_sent_at,
        list_name=default_list_name,
    )
    with pytest.raises(IntegrityError):
        baker.make(
            "boost_mailing_list_tracker.MailingListMessage",
            sender=mailing_list_profile,
            msg_id="<duplicate@example.com>",
            list_name=default_list_name,
            sent_at=sample_sent_at,
        )


# --- Edge cases: empty inputs, optional fields ---


@pytest.mark.django_db
def test_mailing_list_message_optional_fields_can_be_blank(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """MailingListMessage allows blank parent_id, thread_id, subject, content."""
    from boost_mailing_list_tracker import services

    msg, _ = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<minimal@example.com>",
        sent_at=sample_sent_at,
        list_name=default_list_name,
        parent_id="",
        thread_id="",
        subject="",
        content="",
    )
    assert msg.parent_id == ""
    assert msg.thread_id == ""
    assert msg.subject == ""
    assert msg.content == ""


@pytest.mark.django_db
def test_mailing_list_message_sent_at_null_allowed_at_db_level(
    mailing_list_profile,
    default_list_name,
):
    """MailingListMessage.sent_at is nullable (model allows null)."""
    msg = baker.make(
        "boost_mailing_list_tracker.MailingListMessage",
        sender=mailing_list_profile,
        msg_id="<null-sent@example.com>",
        list_name=default_list_name,
        sent_at=None,
    )
    assert msg.sent_at is None
    msg.refresh_from_db()
    assert msg.sent_at is None


# --- Edge cases: max length and boundaries ---


@pytest.mark.django_db
def test_mailing_list_message_msg_id_max_length(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """MailingListMessage accepts msg_id at max_length 255."""
    from boost_mailing_list_tracker import services

    long_id = "x" * 255
    msg, created = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id=long_id,
        sent_at=sample_sent_at,
        list_name=default_list_name,
    )
    assert created is True
    assert len(msg.msg_id) == 255
    assert msg.msg_id == long_id


@pytest.mark.django_db
def test_mailing_list_message_subject_max_length(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """MailingListMessage accepts subject up to 1024 chars."""
    from boost_mailing_list_tracker import services

    long_subject = "s" * 1024
    msg, _ = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<long-subject@example.com>",
        sent_at=sample_sent_at,
        subject=long_subject,
        list_name=default_list_name,
    )
    assert len(msg.subject) == 1024


@pytest.mark.django_db
def test_mailing_list_message_str_truncates_long_subject(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """MailingListMessage __str__ truncates subject to 60 chars."""
    from boost_mailing_list_tracker import services

    long_subject = "A" * 70
    msg, _ = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<long@example.com>",
        sent_at=sample_sent_at,
        subject=long_subject,
        list_name=default_list_name,
    )
    s = str(msg)
    assert len(s) <= 60 + len(default_list_name) + 4  # "list: subject" format
    assert s.startswith(f"{default_list_name}: ")
    assert "A" in s


@pytest.mark.django_db
def test_mailing_list_message_str_exactly_60_char_subject(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """MailingListMessage __str__ with 60-char subject shows full subject."""
    from boost_mailing_list_tracker import services

    subject_60 = "x" * 60
    msg, _ = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<sixty@example.com>",
        sent_at=sample_sent_at,
        subject=subject_60,
        list_name=default_list_name,
    )
    assert subject_60 in str(msg)


# --- Invalid / unexpected data ---


@pytest.mark.django_db
def test_mailing_list_message_invalid_list_name_validation(
    mailing_list_profile,
    sample_sent_at,
):
    """MailingListMessage full_clean() raises ValidationError for invalid list_name."""
    msg = baker.make(
        "boost_mailing_list_tracker.MailingListMessage",
        sender=mailing_list_profile,
        msg_id="<invalid-list@example.com>",
        list_name="not-a-valid-choice",
        sent_at=sample_sent_at,
    )
    with pytest.raises(ValidationError):
        msg.full_clean()


@pytest.mark.django_db
def test_mailing_list_message_empty_msg_id_rejected_by_db(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """Creating MailingListMessage with empty msg_id fails (DB/service constraint)."""
    from boost_mailing_list_tracker import services

    with pytest.raises(ValueError, match="msg_id must not be empty"):
        services.get_or_create_mailing_list_message(
            mailing_list_profile,
            msg_id="",
            sent_at=sample_sent_at,
            list_name=default_list_name,
        )


# --- Meta and table ---


@pytest.mark.django_db
def test_mailing_list_message_meta():
    """MailingListMessage Meta: db_table, ordering, verbose_name."""
    assert (
        MailingListMessage._meta.db_table
        == "boost_mailing_list_tracker_mailinglistmessage"
    )
    assert MailingListMessage._meta.ordering == ["-sent_at"]
    assert MailingListMessage._meta.verbose_name == "Mailing list message"
    assert MailingListMessage._meta.verbose_name_plural == "Mailing list messages"


# --- Relations: CASCADE ---


@pytest.mark.django_db
def test_mailing_list_message_cascade_when_sender_deleted(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """Deleting sender (MailingListProfile) deletes related MailingListMessage (CASCADE)."""
    from boost_mailing_list_tracker import services

    msg, _ = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<cascade@example.com>",
        sent_at=sample_sent_at,
        list_name=default_list_name,
    )
    pk = msg.pk
    profile_pk = mailing_list_profile.pk
    mailing_list_profile.delete()
    assert not MailingListMessage.objects.filter(pk=pk).exists()
    assert not MailingListMessage.objects.filter(sender_id=profile_pk).exists()
