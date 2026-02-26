"""
Fixtures for boost_mailing_list_tracker app.

Depends on cppa_user_tracker (Identity, MailingListProfile).
Writes to MailingListMessage go through boost_mailing_list_tracker.services.
"""

from datetime import datetime, timezone

import pytest
from model_bakery import baker

from boost_mailing_list_tracker.models import MailingListName


@pytest.fixture
def mailing_list_profile(db, identity):
    """MailingListProfile linked to an Identity (sender for messages)."""
    _ = db  # Request DB access; linter expects parameter to be used
    return baker.make(
        "cppa_user_tracker.MailingListProfile",
        identity=identity,
        display_name="Mailing List User",
    )


@pytest.fixture
def make_mailing_list_profile():
    """Factory: create MailingListProfile with optional kwargs."""

    def _make(**kwargs):
        if "identity" not in kwargs:
            kwargs["identity"] = baker.make("cppa_user_tracker.Identity")
        if "display_name" not in kwargs:
            kwargs["display_name"] = "ML User"
        return baker.make("cppa_user_tracker.MailingListProfile", **kwargs)

    return _make


@pytest.fixture
def sample_sent_at():
    """A fixed sent_at datetime for message tests."""
    return datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def default_list_name():
    """Default valid list_name for MailingListMessage."""
    return MailingListName.BOOST_USERS.value
