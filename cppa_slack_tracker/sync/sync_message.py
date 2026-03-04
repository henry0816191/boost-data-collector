"""
Sync Slack messages with the database.

Flow when start_date is None:
  1. Process any existing workspace JSONs for the channel (old → new), remove them.
  2. Determine start_date from the last message datetime in DB (same day, not next day,
     to avoid missing same-day messages). Falls back to today if DB is empty.

Flow always:
  3. end_date defaults to today (UTC) if not given.
  4. Fetch all messages from API for [start_date, end_date]; divide them per day.
  5. For each day: write JSON to workspace and raw (raw is never removed),
     process workspace → save to DB → remove workspace file.

Returns (success_count, error_count).
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from django.db.models import F
from django.db.models.functions import Coalesce

from cppa_slack_tracker.fetcher import fetch_messages
from cppa_slack_tracker.models import SlackChannel, SlackMessage
from cppa_slack_tracker.services import save_slack_message
from cppa_slack_tracker.workspace import (
    get_message_json_path,
    get_raw_message_json_path,
    iter_existing_message_jsons,
)

logger = logging.getLogger(__name__)


def _ts_to_date(ts: Optional[str]) -> Optional[date]:
    """Convert Slack ts string to UTC date, or None if invalid."""
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).date()
    except (ValueError, TypeError, OSError, OverflowError):
        return None


def _messages_by_day(
    messages: list[dict], start_date: date, end_date: date
) -> dict[date, list[dict]]:
    """Group messages by day: a message appears on each day it was created or edited (within range)."""
    by_day: dict[date, list[dict]] = defaultdict(list)
    for msg in messages:
        if not isinstance(msg, dict):
            logger.debug("Skip non-dict message payload: %r", msg)
            continue
        created_d = _ts_to_date(msg.get("ts"))
        if created_d and start_date <= created_d <= end_date:
            by_day[created_d].append(msg)
        edited = msg.get("edited")
        if not isinstance(edited, dict):
            edited = {}
        edited_d = _ts_to_date(edited.get("ts"))
        if edited_d and edited_d != created_d and start_date <= edited_d <= end_date:
            by_day[edited_d].append(msg)
    return dict(by_day)


def _process_message(channel: SlackChannel, msg: dict) -> bool:
    """
    Process one message: save_slack_message. Returns True if saved, False if
    skipped (e.g. ignored subtype). Raises on error.
    """
    return save_slack_message(channel, msg) is not None


def _process_workspace_jsons(channel: SlackChannel) -> tuple[int, int]:
    """
    Process all existing workspace JSONs for the channel in date order (old to new).
    Saves messages to DB and removes each workspace file.
    Returns (success_count, error_count).
    """
    team_slug = channel.team.team_name
    channel_slug = channel.channel_name
    success_count = 0
    error_count = 0
    for path in iter_existing_message_jsons(
        team_slug=team_slug, channel_slug=channel_slug
    ):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                logger.warning(
                    "Unexpected format in %s (not a list); removing file", path
                )
                path.unlink()
                continue
            for msg in data:
                if not isinstance(msg, dict):
                    continue
                try:
                    if _process_message(channel, msg):
                        success_count += 1
                except Exception as e:
                    logger.debug("Skip message %s: %s", msg.get("ts"), e)
                    error_count += 1
            path.unlink()
        except Exception:
            logger.exception("Failed to process %s", path)
    return success_count, error_count


def _last_message_date(channel: SlackChannel) -> Optional[date]:
    """Return the date (UTC) of the most recently updated (or created) message in DB for this channel, or None."""
    last_dt = (
        SlackMessage.objects.filter(channel=channel)
        .annotate(
            effective=Coalesce(
                F("slack_message_updated_at"), F("slack_message_created_at")
            )
        )
        .order_by("-effective")
        .values_list("effective", flat=True)
        .first()
    )
    if last_dt is None:
        return None
    if isinstance(last_dt, datetime):
        return last_dt.astimezone(timezone.utc).date()
    return last_dt


def sync_messages(
    channel: SlackChannel,
    start_date: date | datetime | None = None,
    end_date: date | datetime | None = None,
) -> tuple[int, int]:
    """
    Sync messages for a channel over a date range (UTC).

    If start_date is None:
      - Process existing workspace JSONs (old to new) and remove them.
      - Set start_date to the date of the last message in DB (same day, not next day),
        or today if the DB has no messages for this channel.

    end_date defaults to today (UTC).

    For each day in [start_date, end_date]:
      - Fetch messages from the Slack API.
      - Write JSON to workspace and raw (raw is never deleted).
      - Process workspace JSON → save to DB → remove workspace file.

    Returns (success_count, error_count).
    """
    today = datetime.now(timezone.utc).date()
    success_count = 0
    error_count = 0

    if start_date is not None and isinstance(start_date, datetime):
        start_date = start_date.astimezone(timezone.utc).date()
    if end_date is not None and isinstance(end_date, datetime):
        end_date = end_date.astimezone(timezone.utc).date()
    if end_date is None:
        end_date = today

    # Step 1: process existing workspace JSONs
    if start_date is None:
        s, e = _process_workspace_jsons(channel)
        success_count += s
        error_count += e
        # Step 2: determine start_date from DB (same day as last message)
        last_d = _last_message_date(channel)
        start_date = last_d if last_d is not None else today

    if start_date > end_date:
        return success_count, error_count

    team_slug = channel.team.team_name
    channel_slug = channel.channel_name
    channel_id = channel.channel_id

    # Step 4: fetch all messages for the range, then divide per day
    try:
        all_messages = fetch_messages(channel_id, start_date, end_date)
    except Exception:
        logger.exception(
            "Failed to fetch messages for channel_id=%s (%s..%s)",
            channel_id,
            start_date,
            end_date,
        )
        return success_count, error_count
    messages_by_day = _messages_by_day(all_messages, start_date, end_date)

    # Step 5: for each day with messages, write workspace + raw → process → remove workspace
    d = start_date
    while d <= end_date:
        messages = messages_by_day.get(d, [])
        if not messages:
            d += timedelta(days=1)
            continue

        date_str = d.strftime("%Y-%m-%d")
        workspace_path = get_message_json_path(team_slug, channel_slug, date_str)
        raw_path = get_raw_message_json_path(team_slug, channel_slug, date_str)
        payload = json.dumps(messages, indent=2, default=str)
        try:
            workspace_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            workspace_path.write_text(payload, encoding="utf-8")
            raw_path.write_text(payload, encoding="utf-8")
        except OSError:
            logger.exception(
                "Failed to write JSON for channel_id=%s date=%s", channel_id, date_str
            )
            d += timedelta(days=1)
            continue
        logger.debug(
            "Wrote %s and %s (%s messages)",
            workspace_path,
            raw_path,
            len(messages),
        )

        try:
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                try:
                    if _process_message(channel, msg):
                        success_count += 1
                except Exception as e:
                    logger.debug("Skip message %s: %s", msg.get("ts"), e)
                    error_count += 1
            workspace_path.unlink()
        except Exception:
            logger.exception("Failed to process/remove %s", workspace_path)

        d += timedelta(days=1)

    return success_count, error_count
