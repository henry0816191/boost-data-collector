"""
Management command to run CPPA Slack Tracker.

Syncs Slack data: teams, users, channels, channel memberships, messages.
Uses team_id (required) and optional channel_id. Sync logic lives in
cppa_slack_tracker.sync (sync_user, sync_channel, sync_channel_user, sync_message).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from cppa_slack_tracker.models import SlackChannel, SlackTeam
from cppa_slack_tracker.services import save_slack_message
from cppa_slack_tracker.sync import (
    sync_channel_users,
    sync_channels,
    sync_messages,
    sync_team,
    sync_users,
)

logger = logging.getLogger(__name__)


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO date or YYYY-MM-DD to datetime at start of day UTC."""
    if not date_str or not date_str.strip():
        return None
    date_str = date_str.strip()
    try:
        if "T" in date_str or " " in date_str:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class Command(BaseCommand):
    help = "Run CPPA Slack Tracker to sync Slack data (users, channels, channel memberships, messages)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=str,
            default=None,
            help="Slack team ID. If omitted, uses SLACK_TEAM_ID from .env",
        )
        parser.add_argument(
            "--channel-id",
            type=str,
            default=None,
            help="Slack channel ID (optional). If omitted, sync all channels in the team.",
        )
        parser.add_argument(
            "--start-date",
            type=str,
            default=None,
            help="Start date for message sync (YYYY-MM-DD or ISO). If missing, sync uses latest message date in DB.",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            default=None,
            help="End date for message sync (YYYY-MM-DD or ISO). If missing, today.",
        )
        parser.add_argument(
            "--messages-json",
            type=str,
            default=None,
            help="Path to JSON file or directory of message JSON (legacy; loaded before message sync).",
        )
        parser.add_argument(
            "--sync-users",
            action="store_true",
            help="Sync Slack users",
        )
        parser.add_argument(
            "--sync-channels",
            action="store_true",
            help="Sync Slack channels",
        )
        parser.add_argument(
            "--sync-channel-users",
            action="store_true",
            help="Sync channel memberships",
        )
        parser.add_argument(
            "--sync-messages",
            action="store_true",
            help="Sync Slack messages",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be synced without making changes.",
        )

    def handle(self, *_args, **options):
        team_id = (options.get("team_id") or "").strip()
        if not team_id:
            team_id = (getattr(settings, "SLACK_TEAM_ID", "") or "").strip()
        if not team_id:
            raise CommandError(
                "Team ID is required: set --team-id or SLACK_TEAM_ID in .env"
            )

        dry_run = options.get("dry_run", False)
        if dry_run:
            self._print_dry_run(options, team_id)
            return

        team = sync_team(team_id)

        # Run the requested sync(s). Each of --sync-users, --sync-channels,
        # --sync-channel-users, and --sync-messages runs its corresponding sync
        # when set; multiple flags can be combined. If none are set, default to
        # syncing messages only.
        if options.get("sync_users"):
            self.sync_users(options, team)
        if options.get("sync_channels"):
            self.sync_channels(options, team)
        if options.get("sync_channel_users"):
            self.sync_channel_users(options, team)
        if options.get("sync_messages"):
            self.sync_messages(options, team)

        if (
            not options.get("sync_users")
            and not options.get("sync_channels")
            and not options.get("sync_channel_users")
            and not options.get("sync_messages")
        ):
            self.sync_messages(options, team)

    def _print_dry_run(self, options, team_id: str) -> None:
        """Print what would be synced when --dry-run is set."""
        self.stdout.write(self.style.WARNING("Dry run: no changes will be made."))
        self.stdout.write(f"  Team ID: {team_id}")
        channel_id = (options.get("channel_id") or "").strip() or None
        if channel_id:
            self.stdout.write(f"  Channel ID: {channel_id}")
        printed = False
        if options.get("sync_users"):
            self.stdout.write("  Would run: sync users")
            printed = True
        if options.get("sync_channels"):
            self.stdout.write(
                "  Would run: sync channels"
                + (f" (channel_id={channel_id})" if channel_id else " (all channels)")
            )
            printed = True
        if options.get("sync_channel_users"):
            self.stdout.write(
                "  Would run: sync channel memberships"
                + (f" (channel_id={channel_id})" if channel_id else " (all channels)")
            )
            printed = True
        if options.get("sync_messages"):
            start_str = (options.get("start_date") or "").strip() or "from DB or today"
            end_str = (options.get("end_date") or "").strip() or "today"
            self.stdout.write(
                f"  Would run: sync messages (start={start_str}, end={end_str})"
            )
            if options.get("messages_json"):
                self.stdout.write(
                    f"  Would load legacy messages from: {options.get('messages_json')}"
                )
            printed = True
        if printed:
            return
        self.stdout.write("  Would run: sync messages only (default)")
        if channel_id:
            self.stdout.write(f"    (channel_id={channel_id})")
        start_str = (options.get("start_date") or "").strip() or "from DB or today"
        end_str = (options.get("end_date") or "").strip() or "today"
        self.stdout.write(f"    start={start_str}, end={end_str}")

    def sync_users(self, _options, team: SlackTeam):
        """Sync users via sync.sync_users (workspace users.json or fetch_user_list)."""
        team_slug = team.team_name
        self.stdout.write(
            f"Syncing users (team_slug={team_slug}, team_id={team.team_id})..."
        )
        success_count, error_count = sync_users(
            team_slug,
            team_id=team.team_id,
            include_bots=True,
        )
        self.stdout.write(
            self.style.SUCCESS(f"Synced {success_count} users, {error_count} errors")
        )

    def sync_channels(self, options, team: SlackTeam):
        """Sync channels via sync.sync_channels (workspace channels.json or fetch_channel_list)."""
        channel_id = (options.get("channel_id") or "").strip() or None
        self.stdout.write("Syncing channels...")
        success_count, error_count = sync_channels(
            team,
            channel_id=channel_id,
            team_id=team.team_id,
        )
        self.stdout.write(
            self.style.SUCCESS(f"Synced {success_count} channels, {error_count} errors")
        )

    def sync_channel_users(self, options, team: SlackTeam):
        """Sync channel memberships via sync.sync_channel_users."""
        channel_id = (options.get("channel_id") or "").strip() or None
        self.stdout.write("Syncing channel memberships...")
        success_count, error_count = sync_channel_users(
            team,
            channel_id=channel_id,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Synced {success_count} channel member lists, {error_count} errors"
            )
        )

    def _channels_to_sync(self, options, team: SlackTeam) -> list[SlackChannel]:
        """Return list of channels to sync messages for (one or all in team)."""
        channel_id = (options.get("channel_id") or "").strip() or None
        if channel_id:
            try:
                return [SlackChannel.objects.get(team=team, channel_id=channel_id)]
            except SlackChannel.DoesNotExist:
                logger.warning(
                    "Channel %s not found. Syncing all channels in team.",
                    channel_id,
                )
        return list(SlackChannel.objects.filter(team=team).order_by("channel_id"))

    def _load_messages_from_json_path(self, path: str) -> list[dict]:
        """Load message dicts from a JSON file or from JSON files in a directory."""
        messages = []

        def _append_payload(data):
            if isinstance(data, list):
                messages.extend(data)
            else:
                messages.append(data)

        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                _append_payload(data)
            except (OSError, json.JSONDecodeError):
                logger.exception("Failed to load legacy messages JSON: %s", path)
        elif os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                if name.endswith(".json"):
                    file_path = os.path.join(path, name)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        _append_payload(data)
                    except (OSError, json.JSONDecodeError):
                        logger.exception(
                            "Skipping invalid legacy messages JSON: %s", file_path
                        )
        return messages

    def sync_messages(self, options, team: SlackTeam):
        """
        Sync messages via sync.sync_messages (workspace JSONs, then fetch by day).
        Optional legacy: load from --messages-json path and save to DB first.
        """
        channels = self._channels_to_sync(options, team)
        if not channels:
            self.stdout.write(
                self.style.WARNING("No channels to sync. Sync channels first.")
            )
            return

        start_date_str = (options.get("start_date") or "").strip() or None
        end_date_str = (options.get("end_date") or "").strip() or None
        messages_json_path = (options.get("messages_json") or "").strip() or None

        start_dt = _parse_date(start_date_str)
        end_dt = _parse_date(end_date_str)

        if messages_json_path and os.path.exists(messages_json_path):
            all_loaded = self._load_messages_from_json_path(messages_json_path)
            if all_loaded:
                self.stdout.write(
                    f"Loaded {len(all_loaded)} message(s) from --messages-json; saving to DB..."
                )
                channel_by_id = {c.channel_id: c for c in channels}
                load_failures = 0
                for msg in all_loaded:
                    if not isinstance(msg, dict):
                        load_failures += 1
                        logger.warning(
                            "Skipping non-dict payload from --messages-json: %r",
                            msg,
                        )
                        continue
                    ch_id = msg.get("channel")
                    channel = channel_by_id.get(ch_id) if ch_id else None
                    if not channel:
                        load_failures += 1
                        logger.warning(
                            "Skipping message from --messages-json with unknown channel_id=%s ts=%s",
                            ch_id,
                            msg.get("ts", msg.get("client_msg_id", "?")),
                        )
                        continue
                    try:
                        save_slack_message(channel, msg)
                    except Exception:
                        msg_ts = msg.get("ts", msg.get("client_msg_id", "?"))
                        logger.exception(
                            "Failed to save message from --messages-json: channel_id=%s ts=%s",
                            ch_id,
                            msg_ts,
                        )
                        load_failures += 1
                if load_failures:
                    self.stdout.write(
                        self.style.WARNING(
                            f"{load_failures} message(s) failed to import from --messages-json."
                        )
                    )

        start_d = start_dt.date() if start_dt is not None else None
        end_d = end_dt.date() if end_dt is not None else None

        self.stdout.write("Syncing messages per channel...")
        for channel in channels:
            s, e = sync_messages(channel, start_date=start_d, end_date=end_d)
            self.stdout.write(
                self.style.SUCCESS(f"  #{channel.channel_name}: {s} saved, {e} errors")
            )
