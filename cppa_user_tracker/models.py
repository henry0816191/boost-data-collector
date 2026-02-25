"""
Models per docs/Schema.md section 1: Base tables, Identity, and profiles.
"""

from django.db import models


class ProfileType(models.TextChoices):
    GITHUB = "github", "GitHub"
    SLACK = "slack", "Slack"
    MAILING_LIST = "mailing_list", "Mailing list"
    WG21 = "wg21", "WG21"
    DISCORD = "discord", "Discord"


class GitHubAccountType(models.TextChoices):
    USER = "user", "User"
    ORGANIZATION = "organization", "Organization"
    ENTERPRISE = "enterprise", "Enterprise"


class Identity(models.Model):
    """Canonical user/account; one identity can have multiple BaseProfiles."""

    display_name = models.CharField(max_length=255, db_index=True, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Identity"
        verbose_name_plural = "Identities"
        ordering = ["id"]


class TmpIdentity(models.Model):
    """Temporary identity for staging (CPPA User Tracker); merged into Identity later."""

    display_name = models.CharField(max_length=255, db_index=True, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "Temporary identity"
        verbose_name_plural = "Temporary identities"


class BaseProfile(models.Model):
    """Base table for profiles; extended by platform-specific profile tables."""

    identity = models.ForeignKey(
        Identity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="profiles",
        db_column="identity_id",
    )
    type = models.CharField(
        max_length=20,
        choices=ProfileType.choices,
        db_index=True,
    )

    class Meta:
        abstract = False


class TempProfileIdentityRelation(models.Model):
    """Staging table: base_profile_id -> target_identity_id (CPPA User Tracker)."""

    base_profile = models.ForeignKey(
        BaseProfile,
        on_delete=models.CASCADE,
        related_name="temp_identity_relations",
        db_column="base_profile_id",
    )
    target_identity = models.ForeignKey(
        TmpIdentity,
        on_delete=models.CASCADE,
        related_name="temp_profile_relations",
        db_column="target_identity_id",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "Temporary profile-identity relation"
        verbose_name_plural = "Temporary profile-identity relations"


class Email(models.Model):
    """Email addresses linked to BaseProfile (one profile, many emails)."""

    base_profile = models.ForeignKey(
        BaseProfile,
        on_delete=models.CASCADE,
        related_name="emails",
        db_column="base_profile_id",
    )
    email = models.CharField(max_length=255, db_index=True)
    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class GitHubAccount(BaseProfile):
    """Profile for GitHub (user/org/enterprise); extends BaseProfile."""

    def save(self, *args, **kwargs):
        self.type = ProfileType.GITHUB
        super().save(*args, **kwargs)

    github_account_id = models.BigIntegerField(db_index=True)
    username = models.CharField(max_length=255, db_index=True, blank=True)
    display_name = models.CharField(max_length=255, db_index=True, blank=True)
    avatar_url = models.URLField(max_length=512, blank=True)
    account_type = models.CharField(
        max_length=20,
        choices=GitHubAccountType.choices,
        db_index=True,
        default=GitHubAccountType.USER,
        db_column="account_type",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class SlackUser(BaseProfile):
    """Profile for Slack; extends BaseProfile."""

    def save(self, *args, **kwargs):
        self.type = ProfileType.SLACK
        super().save(*args, **kwargs)

    slack_user_id = models.CharField(max_length=64, db_index=True)
    username = models.CharField(max_length=255, db_index=True, blank=True)
    display_name = models.CharField(max_length=255, db_index=True, blank=True)
    avatar_url = models.URLField(max_length=512, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class MailingListProfile(BaseProfile):
    """Profile for mailing list; extends BaseProfile."""

    def save(self, *args, **kwargs):
        self.type = ProfileType.MAILING_LIST
        super().save(*args, **kwargs)

    display_name = models.CharField(max_length=255, db_index=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class WG21PaperAuthorProfile(BaseProfile):
    """Profile for WG21 paper authors; extends BaseProfile."""

    def save(self, *args, **kwargs):
        self.type = ProfileType.WG21
        super().save(*args, **kwargs)

    display_name = models.CharField(max_length=255, db_index=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class DiscordProfile(BaseProfile):
    """Profile for Discord; extends BaseProfile."""

    def save(self, *args, **kwargs):
        self.type = ProfileType.DISCORD
        super().save(*args, **kwargs)

    discord_user_id = models.BigIntegerField(unique=True, db_index=True)
    username = models.CharField(max_length=255, db_index=True, blank=True)
    display_name = models.CharField(max_length=255, db_index=True, blank=True)
    avatar_url = models.URLField(max_length=512, blank=True)
    is_bot = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
