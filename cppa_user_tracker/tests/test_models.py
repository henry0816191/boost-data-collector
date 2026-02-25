"""Tests for cppa_user_tracker models."""

import pytest
from model_bakery import baker

from cppa_user_tracker.models import (
    GitHubAccountType,
    ProfileType,
)


# --- Identity ---


@pytest.mark.django_db
def test_identity_creation(make_identity):
    """Identity can be created with display_name."""
    identity = make_identity(display_name="Dev User")
    assert identity.display_name == "Dev User"
    assert identity.id is not None


@pytest.mark.django_db
def test_identity_with_description(make_identity):
    """Identity stores description."""
    identity = make_identity(display_name="Dev", description="A developer")
    assert identity.description == "A developer"


@pytest.mark.django_db
def test_identity_blank_display_name(make_identity):
    """Identity allows blank display_name."""
    identity = make_identity(display_name="")
    assert identity.display_name == ""
    assert identity.id is not None


@pytest.mark.django_db
def test_identity_has_timestamps(make_identity):
    """Identity has created_at and updated_at set."""
    identity = make_identity(display_name="Timed")
    assert identity.created_at is not None
    assert identity.updated_at is not None


# --- GitHubAccount ---


@pytest.mark.django_db
def test_github_account_sets_profile_type(github_account):
    """GitHubAccount.save() sets type to GITHUB."""
    assert github_account.type == ProfileType.GITHUB
    assert github_account.username == "testuser"


@pytest.mark.django_db
def test_github_account_identity_relation(github_account, identity):
    """GitHubAccount is linked to Identity."""
    assert github_account.identity_id == identity.id
    assert identity.profiles.filter(pk=github_account.pk).exists()


@pytest.mark.django_db
def test_github_account_type_user_org(make_github_account, identity):
    """GitHubAccount stores account_type USER and ORGANIZATION."""
    user_acc = make_github_account(
        identity=identity, account_type=GitHubAccountType.USER
    )
    assert user_acc.account_type == GitHubAccountType.USER
    org_acc = make_github_account(
        identity=identity,
        github_account_id=88888,
        account_type=GitHubAccountType.ORGANIZATION,
    )
    assert org_acc.account_type == GitHubAccountType.ORGANIZATION


@pytest.mark.django_db
def test_github_account_avatar_and_display_name(make_github_account, identity):
    """GitHubAccount stores avatar_url and display_name."""
    acc = make_github_account(
        identity=identity,
        display_name="Display",
        avatar_url="https://example.com/avatar.png",
    )
    assert acc.display_name == "Display"
    assert acc.avatar_url == "https://example.com/avatar.png"


# --- TmpIdentity ---


@pytest.mark.django_db
def test_tmp_identity_creation(make_tmp_identity):
    """TmpIdentity can be created with display_name."""
    tmp = make_tmp_identity(display_name="Staging User")
    assert tmp.display_name == "Staging User"
    assert tmp.id is not None


@pytest.mark.django_db
def test_tmp_identity_with_description(make_tmp_identity):
    """TmpIdentity stores description."""
    tmp = make_tmp_identity(display_name="Staging", description="Staging record")
    assert tmp.description == "Staging record"


@pytest.mark.django_db
def test_tmp_identity_has_timestamps(tmp_identity):
    """TmpIdentity has created_at and updated_at."""
    assert tmp_identity.created_at is not None
    assert tmp_identity.updated_at is not None


# --- SlackUser ---


@pytest.mark.django_db
def test_slack_user_sets_profile_type(identity):
    """SlackUser.save() sets type to SLACK."""
    slack = baker.make(
        "cppa_user_tracker.SlackUser",
        identity=identity,
        slack_user_id="U123",
        username="slackuser",
    )
    assert slack.type == ProfileType.SLACK


@pytest.mark.django_db
def test_slack_user_identity_relation(identity):
    """SlackUser is linked to Identity."""
    slack = baker.make(
        "cppa_user_tracker.SlackUser",
        identity=identity,
        slack_user_id="U456",
    )
    assert slack.identity_id == identity.id
    assert identity.profiles.filter(pk=slack.pk).exists()


@pytest.mark.django_db
def test_slack_user_display_name(identity):
    """SlackUser stores display_name."""
    slack = baker.make(
        "cppa_user_tracker.SlackUser",
        identity=identity,
        slack_user_id="U789",
        display_name="Slack Display",
    )
    assert slack.display_name == "Slack Display"


# --- MailingListProfile ---


@pytest.mark.django_db
def test_mailing_list_profile_sets_type(identity):
    """MailingListProfile.save() sets type to MAILING_LIST."""
    ml = baker.make(
        "cppa_user_tracker.MailingListProfile",
        identity=identity,
        display_name="list-user",
    )
    assert ml.type == ProfileType.MAILING_LIST


@pytest.mark.django_db
def test_mailing_list_profile_identity_relation(identity):
    """MailingListProfile is linked to Identity."""
    ml = baker.make(
        "cppa_user_tracker.MailingListProfile",
        identity=identity,
        display_name="ml-user",
    )
    assert ml.identity_id == identity.id


@pytest.mark.django_db
def test_mailing_list_profile_display_name(identity):
    """MailingListProfile stores display_name."""
    ml = baker.make(
        "cppa_user_tracker.MailingListProfile",
        identity=identity,
        display_name="wg21-list",
    )
    assert ml.display_name == "wg21-list"


# --- WG21PaperAuthorProfile ---


@pytest.mark.django_db
def test_wg21_profile_sets_type(identity):
    """WG21PaperAuthorProfile.save() sets type to WG21."""
    wg = baker.make(
        "cppa_user_tracker.WG21PaperAuthorProfile",
        identity=identity,
        display_name="Paper Author",
    )
    assert wg.type == ProfileType.WG21


@pytest.mark.django_db
def test_wg21_profile_identity_relation(identity):
    """WG21PaperAuthorProfile is linked to Identity."""
    wg = baker.make(
        "cppa_user_tracker.WG21PaperAuthorProfile",
        identity=identity,
        display_name="Author",
    )
    assert wg.identity_id == identity.id


@pytest.mark.django_db
def test_wg21_profile_display_name(identity):
    """WG21PaperAuthorProfile stores display_name."""
    wg = baker.make(
        "cppa_user_tracker.WG21PaperAuthorProfile",
        identity=identity,
        display_name="John Doe",
    )
    assert wg.display_name == "John Doe"


# --- Email ---


@pytest.mark.django_db
def test_email_linked_to_profile(github_account):
    """Email is linked to BaseProfile via base_profile."""
    email_obj = baker.make(
        "cppa_user_tracker.Email",
        base_profile=github_account,
        email="dev@example.com",
    )
    assert email_obj.base_profile_id == github_account.id
    assert github_account.emails.filter(email="dev@example.com").exists()


@pytest.mark.django_db
def test_email_is_primary_and_active(github_account):
    """Email stores is_primary and is_active."""
    primary = baker.make(
        "cppa_user_tracker.Email",
        base_profile=github_account,
        email="primary@example.com",
        is_primary=True,
        is_active=True,
    )
    assert primary.is_primary is True
    assert primary.is_active is True


@pytest.mark.django_db
def test_email_has_timestamps(github_account):
    """Email has created_at and updated_at."""
    email_obj = baker.make(
        "cppa_user_tracker.Email",
        base_profile=github_account,
        email="t@example.com",
    )
    assert email_obj.created_at is not None
    assert email_obj.updated_at is not None


# --- TempProfileIdentityRelation ---


@pytest.mark.django_db
def test_temp_relation_links_profile_and_tmp_identity(github_account, tmp_identity):
    """TempProfileIdentityRelation links BaseProfile to TmpIdentity."""
    rel = baker.make(
        "cppa_user_tracker.TempProfileIdentityRelation",
        base_profile=github_account,
        target_identity=tmp_identity,
    )
    assert rel.base_profile_id == github_account.id
    assert rel.target_identity_id == tmp_identity.id


@pytest.mark.django_db
def test_temp_relation_reverse_relations(github_account, tmp_identity):
    """TempProfileIdentityRelation accessible from profile and tmp_identity."""
    rel = baker.make(
        "cppa_user_tracker.TempProfileIdentityRelation",
        base_profile=github_account,
        target_identity=tmp_identity,
    )
    assert rel in github_account.temp_identity_relations.all()
    assert rel in tmp_identity.temp_profile_relations.all()


@pytest.mark.django_db
def test_temp_relation_has_timestamps(github_account, tmp_identity):
    """TempProfileIdentityRelation has created_at and updated_at."""
    rel = baker.make(
        "cppa_user_tracker.TempProfileIdentityRelation",
        base_profile=github_account,
        target_identity=tmp_identity,
    )
    assert rel.created_at is not None
    assert rel.updated_at is not None
