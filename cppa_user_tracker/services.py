"""
Service layer for cppa_user_tracker.

All creates/updates/deletes for this app's models must go through functions in this
module. Do not call Model.objects.create(), model.save(), or model.delete() from
outside this module (e.g. from management commands, views, or other apps).

See docs/Contributing.md for the project-wide rule.
"""
from __future__ import annotations

from typing import Any, Optional, Protocol

from django.db.models import Min

from .models import (
    BaseProfile,
    Email,
    Identity,
    TempProfileIdentityRelation,
    TmpIdentity,
)


# --- Identity ---
def create_identity(
    display_name: str = "",
    description: str = "",
) -> Identity:
    """Create an Identity. Returns the new Identity."""
    return Identity.objects.create(
        display_name=display_name,
        description=description,
    )


def get_or_create_identity(
    display_name: str = "",
    description: str = "",
    defaults: Optional[dict[str, Any]] = None,
) -> tuple[Identity, bool]:
    """Get or create an Identity by display_name. If exists, updates description from defaults."""
    lookup = {"display_name": display_name}
    defaults = defaults or {"description": description}
    identity, created = Identity.objects.get_or_create(defaults=defaults, **lookup)
    if not created and "description" in defaults and identity.description != defaults["description"]:
        identity.description = defaults["description"]
        identity.save(update_fields=["description"])
    return identity, created


# --- TmpIdentity ---
def create_tmp_identity(
    display_name: str = "",
    description: str = "",
) -> TmpIdentity:
    """Create a TmpIdentity (staging). Returns the new TmpIdentity."""
    return TmpIdentity.objects.create(
        display_name=display_name,
        description=description,
    )


# --- TempProfileIdentityRelation (staging) ---
def add_temp_profile_identity_relation(
    base_profile: BaseProfile,
    target_identity: TmpIdentity,
) -> tuple[TempProfileIdentityRelation, bool]:
    """Link a BaseProfile to a TmpIdentity (staging). Returns (relation, created)."""
    return TempProfileIdentityRelation.objects.get_or_create(
        base_profile=base_profile,
        target_identity=target_identity,
    )


def remove_temp_profile_identity_relation(
    base_profile: BaseProfile,
    target_identity: TmpIdentity,
) -> None:
    """Remove the staging relation between base_profile and target_identity."""
    TempProfileIdentityRelation.objects.filter(
        base_profile=base_profile,
        target_identity=target_identity,
    ).delete()


# --- Email ---
def add_email(
    base_profile: BaseProfile,
    email: str,
    is_primary: bool = False,
    is_active: bool = True,
) -> Email:
    """Add an email to a BaseProfile. Returns the new Email."""
    return Email.objects.create(
        base_profile=base_profile,
        email=email,
        is_primary=is_primary,
        is_active=is_active,
    )


def update_email(email_obj: Email, **kwargs: Any) -> Email:
    """Update an Email instance. Allowed keys: email, is_primary, is_active."""
    for key in ("email", "is_primary", "is_active"):
        if key in kwargs:
            setattr(email_obj, key, kwargs[key])
    email_obj.save()
    return email_obj


def remove_email(email_obj: Email) -> None:
    """Remove an email from a profile."""
    email_obj.delete()


# --- BaseProfile / subclasses ---
from .models import GitHubAccount, GitHubAccountType, MailingListProfile


def get_or_create_mailing_list_profile(
    display_name: str = "",
    email: str = "",
) -> tuple[MailingListProfile, bool]:
    """Get or create a MailingListProfile by display_name and email. Returns (profile, created).

    Mailing list has no external id; we identify by display_name + email. Looks up a profile
    that has this display_name and an Email with this address. If found, returns that profile.
    Otherwise creates a new MailingListProfile, adds the email, and returns the new profile.

    Raises ValueError if display_name or email is missing or empty after stripping.
    """
    display_name_val = (display_name or "").strip()
    email_val = (email or "").strip()
    if not display_name_val:
        raise ValueError("display_name must not be empty.")
    if not email_val:
        raise ValueError("email must not be empty.")

    profile = (
        MailingListProfile.objects.filter(
            display_name=display_name_val,
            emails__email=email_val,
        )
        .distinct()
        .first()
    )
    if profile is not None:
        return profile, False

    profile = MailingListProfile.objects.create(
        display_name=display_name_val,
    )
    add_email(profile, email_val, is_primary=True)
    return profile, True


def get_or_create_github_account(
    github_account_id: int,
    username: str = "",
    display_name: str = "",
    avatar_url: str = "",
    account_type: str = GitHubAccountType.USER,
    identity: Optional[Identity] = None,
) -> tuple[GitHubAccount, bool]:
    """Get or create a GitHubAccount by github_account_id. Returns (account, created).

    If account exists, updates username, display_name, avatar_url, account_type if provided.
    identity is only set on creation; to update identity use a separate service function.
    """
    # API/user data can be None; store as empty string for NOT NULL columns.
    username_val = username or ""
    display_name_val = display_name or ""
    avatar_url_val = avatar_url or ""
    account, created = GitHubAccount.objects.get_or_create(
        github_account_id=github_account_id,
        defaults={
            "username": username_val,
            "display_name": display_name_val,
            "avatar_url": avatar_url_val,
            "account_type": account_type,
            "identity": identity,
        },
    )
    if not created:
        # Update fields if not newly created
        account.username = username_val or account.username
        account.display_name = display_name_val or account.display_name
        account.avatar_url = avatar_url_val or account.avatar_url
        account.account_type = account_type
        account.save()
    return account, created


class GitHubClientProtocol(Protocol):
    """Protocol for a GitHub API client used by get_or_create_owner_account."""

    def rest_request(self, path: str) -> dict[str, Any]: ...


def get_or_create_owner_account(client: GitHubClientProtocol, owner: str) -> GitHubAccount:
    """Get or create a GitHubAccount for an owner (org or user). For use by any app.

    Checks DB first by username to avoid unnecessary API calls. Uses GET /users/{owner}
    (GitHub returns both users and orgs with a \"type\" field). Returns the GitHubAccount.
    """
    existing = GitHubAccount.objects.filter(username=owner).first()
    if existing is not None:
        return existing
    data = client.rest_request(f"/users/{owner}")
    api_type = (data.get("type") or "User").strip().lower()
    account_type_map = {
        "organization": GitHubAccountType.ORGANIZATION,
        "user": GitHubAccountType.USER,
        "enterprise": GitHubAccountType.ENTERPRISE,
    }
    account_type = account_type_map.get(api_type, GitHubAccountType.USER)
    account = get_or_create_github_account(
        github_account_id=data["id"],
        username=data.get("login") or owner,
        display_name=data.get("name") or "",
        avatar_url=data.get("avatar_url") or "",
        account_type=account_type,
    )[0]
    email_str = (data.get("email") or "").strip()
    if email_str and not account.emails.filter(email=email_str).exists():
        add_email(account, email_str, is_primary=not account.emails.exists())
    return account


def _get_next_negative_github_account_id() -> int:
    """Return the next negative id for synthetic/unknown accounts (-1, -2, ...)."""
    r = GitHubAccount.objects.filter(github_account_id__lt=0).aggregate(
        Min("github_account_id")
    )
    min_id = r.get("github_account_id__min")
    return (min_id - 1) if min_id is not None else -1


def get_or_create_unknown_github_account(
    name: Optional[str] = None,
    email: str = "",
) -> tuple[GitHubAccount, bool]:
    """Get or create a GitHubAccount for commits with no API author/committer.

    Uses display_name for lookup; if None/empty, uses \"unknown\". Checks DB for an
    existing account with that display_name and negative github_account_id first; if
    found, returns it (and adds email if provided and not already present). Otherwise
    creates a new account with id -1, -2, etc. Returns (account, created).
    """
    display_name = (name or "").strip() or "unknown"
    email_str = (email or "").strip()
    existing = GitHubAccount.objects.filter(
        display_name=display_name, github_account_id__lt=0
    ).first()
    if existing is not None:
        if email_str and not existing.emails.filter(email=email_str).exists():
            add_email(existing, email_str, is_primary=not existing.emails.exists())
        return existing, False
    next_id = _get_next_negative_github_account_id()
    account = get_or_create_github_account(
        github_account_id=next_id,
        username=display_name,
        display_name=display_name,
        avatar_url="",
    )[0]
    if email_str:
        add_email(account, email_str, is_primary=True)
    return account, True
