"""Tests for boost_mailing_list_tracker.preprocesser."""

from datetime import timedelta

import pytest
from django.utils import timezone

from boost_mailing_list_tracker.preprocesser import (
    preprocess_mailing_list_for_pinecone,
)


@pytest.mark.django_db
def test_preprocesser_returns_empty_when_no_messages():
    """No source rows -> empty docs and is_chunked=False."""
    docs, is_chunked = preprocess_mailing_list_for_pinecone([], None)
    assert docs == []
    assert is_chunked is False


@pytest.mark.django_db
def test_preprocesser_first_sync_returns_all_messages(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """final_sync_at=None returns all messages on first run."""
    from boost_mailing_list_tracker import services

    services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<a@example.com>",
        sent_at=sample_sent_at,
        subject="Subject A",
        content="Body A",
        list_name=default_list_name,
    )
    services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<b@example.com>",
        sent_at=sample_sent_at,
        subject="Subject B",
        content="Body B",
        list_name=default_list_name,
    )

    docs, is_chunked = preprocess_mailing_list_for_pinecone([], None)
    assert is_chunked is False
    assert len(docs) == 2
    doc_ids = {d["metadata"]["doc_id"] for d in docs}
    assert doc_ids == {"<a@example.com>", "<b@example.com>"}


@pytest.mark.django_db
def test_preprocesser_incremental_by_created_at(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """Only messages created after final_sync_at are included for incremental runs."""
    from boost_mailing_list_tracker import services
    from boost_mailing_list_tracker.models import MailingListMessage

    old_msg, _ = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<old@example.com>",
        sent_at=sample_sent_at,
        subject="Old",
        content="Old body",
        list_name=default_list_name,
    )
    new_msg, _ = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<new@example.com>",
        sent_at=sample_sent_at,
        subject="New",
        content="New body",
        list_name=default_list_name,
    )

    now = timezone.now()
    MailingListMessage.objects.filter(pk=old_msg.pk).update(
        created_at=now - timedelta(days=2)
    )
    MailingListMessage.objects.filter(pk=new_msg.pk).update(
        created_at=now - timedelta(hours=1)
    )

    docs, _ = preprocess_mailing_list_for_pinecone([], now - timedelta(days=1))
    assert len(docs) == 1
    assert docs[0]["metadata"]["doc_id"] == "<new@example.com>"


@pytest.mark.django_db
def test_preprocesser_retries_failed_ids_even_if_old(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """failed_ids are re-included even when older than final_sync_at."""
    from boost_mailing_list_tracker import services
    from boost_mailing_list_tracker.models import MailingListMessage

    retry_msg, _ = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<retry@example.com>",
        sent_at=sample_sent_at,
        subject="Retry",
        content="Retry body",
        list_name=default_list_name,
    )
    now = timezone.now()
    MailingListMessage.objects.filter(pk=retry_msg.pk).update(
        created_at=now - timedelta(days=10)
    )

    docs, _ = preprocess_mailing_list_for_pinecone(
        failed_ids=["<retry@example.com>"],
        final_sync_at=now - timedelta(days=1),
    )
    assert len(docs) == 1
    assert docs[0]["metadata"]["doc_id"] == "<retry@example.com>"
    assert docs[0]["metadata"]["table_ids"] == retry_msg.pk


@pytest.mark.django_db
def test_preprocesser_deduplicates_overlap_between_failed_and_incremental(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """Same message in failed_ids and incremental set is emitted once."""
    from boost_mailing_list_tracker import services
    from boost_mailing_list_tracker.models import MailingListMessage

    msg, _ = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<dedupe@example.com>",
        sent_at=sample_sent_at,
        subject="Dedupe",
        content="Dedupe body",
        list_name=default_list_name,
    )
    now = timezone.now()
    MailingListMessage.objects.filter(pk=msg.pk).update(created_at=now)

    docs, _ = preprocess_mailing_list_for_pinecone(
        failed_ids=["<dedupe@example.com>", "  <dedupe@example.com>  "],
        final_sync_at=now - timedelta(days=1),
    )
    assert len(docs) == 1
    assert docs[0]["metadata"]["doc_id"] == "<dedupe@example.com>"


@pytest.mark.django_db
def test_preprocesser_document_shape_and_metadata_fields(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """Each output item has required top-level keys and guideline-compatible metadata."""
    from boost_mailing_list_tracker import services

    msg, _ = services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<shape@example.com>",
        sent_at=sample_sent_at,
        parent_id="<parent@example.com>",
        thread_id="thread-1",
        subject="Shape subject",
        content="Shape body",
        list_name=default_list_name,
    )

    docs, is_chunked = preprocess_mailing_list_for_pinecone([], None)
    assert is_chunked is False
    target = next(d for d in docs if d["metadata"]["doc_id"] == msg.msg_id)

    assert isinstance(target["content"], str)
    assert target["content"] != ""
    assert "metadata" in target
    assert target["metadata"]["doc_id"] == "<shape@example.com>"
    assert target["metadata"]["table_ids"] == msg.pk
    assert target["metadata"]["type"] == "mailing"
    assert target["metadata"]["thread_id"] == "thread-1"
    assert target["metadata"]["parent_id"] == "<parent@example.com>"
    assert target["metadata"]["author"] == mailing_list_profile.display_name
    assert target["metadata"]["subject"] == "Shape subject"
    assert target["metadata"]["list_name"] == default_list_name
    assert target["metadata"]["timestamp"] == int(sample_sent_at.timestamp())
    assert "ids" not in target["metadata"]
    assert "msg_id" not in target["metadata"]
    assert "source" not in target["metadata"]
    assert "sender_id" not in target["metadata"]
    assert "Subject: Shape subject" in target["content"]
    assert "Shape body" in target["content"]


@pytest.mark.django_db
def test_preprocesser_handles_empty_body_with_metadata_fallback_content(
    mailing_list_profile,
    default_list_name,
    sample_sent_at,
):
    """Even with empty body, the generated content keeps useful metadata text."""
    from boost_mailing_list_tracker import services

    services.get_or_create_mailing_list_message(
        mailing_list_profile,
        msg_id="<empty-body@example.com>",
        sent_at=sample_sent_at,
        subject="",
        content="",
        list_name=default_list_name,
    )

    docs, _ = preprocess_mailing_list_for_pinecone([], None)
    target = next(
        d for d in docs if d["metadata"]["doc_id"] == "<empty-body@example.com>"
    )
    assert "List: " in target["content"]
    assert "Sent At: " in target["content"]
