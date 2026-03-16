"""
Sync Slack messages with the database.

Flow when start_date is None:
  1. Process any existing workspace JSONs for the channel (old → new), remove them.
  2. Determine start_date: same day as last message in DB (to avoid missing same-day
     messages). If DB has no messages, pass start_date=None so the API is called
     without oldest (fetch from beginning of channel up to end_date).

Flow always:
  3. end_date defaults to today (UTC) if not given.
  4. Fetch messages from API ([start_date, end_date] or all up to end_date if start_date None).
  5. For each day: write JSON to workspace; merge into raw (by ts); process → save to DB → remove workspace file.

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


def _merge_messages_by_ts(
    existing_list: list[dict], new_messages: list[dict]
) -> list[dict]:
    """Merge new_messages into existing_list by ts: same ts → update, new ts → add. Returns list sorted by ts."""
    by_ts: dict[str, dict] = {}
    for msg in existing_list:
        if isinstance(msg, dict) and msg.get("ts"):
            by_ts[msg["ts"]] = msg
    for msg in new_messages:
        if isinstance(msg, dict) and msg.get("ts"):
            by_ts[msg["ts"]] = msg
    return sorted(by_ts.values(), key=lambda m: m.get("ts") or "")


def sync_messages(
    channel: SlackChannel,
    start_date: date | datetime | None = None,
    end_date: date | datetime | None = None,
) -> tuple[int, int]:
    """
    Sync messages for a channel over a date range (UTC).

    If start_date is None:
      - Process existing workspace JSONs (old to new) and remove them.
      - Set start_date to the date of the last message in DB (same day), or leave
        None if DB has no messages (fetch from beginning of channel; API called without oldest).

    end_date defaults to today (UTC).

    For each day in the fetched range:
      - Write JSON to workspace. Merge into raw file by ts (same ts → update, new ts → add).
      - Process workspace → save to DB → remove workspace file.

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

    # Step 1: process existing workspace JSONs (old → new), remove them
    if start_date is None:
        s, e = _process_workspace_jsons(channel)
        success_count += s
        error_count += e
        # Determine start_date: same day as last message, or None to fetch from beginning
        last_d = _last_message_date(channel)
        start_date = last_d if last_d is not None else None

    if start_date is not None and start_date > end_date:
        return success_count, error_count

    team_slug = channel.team.team_name
    channel_slug = channel.channel_name
    channel_id = channel.channel_id

    # Step 2: fetch messages ([start_date, end_date] or all up to end_date if start_date is None)
    try:
        all_messages = fetch_messages(
            channel_id, start_date, end_date, team_id=channel.team.team_id
        )
    except Exception:
        logger.exception(
            "Failed to fetch messages for channel_id=%s (%s..%s)",
            channel_id,
            start_date,
            end_date,
        )
        return success_count, error_count

    if not all_messages:
        return success_count, error_count

    # When we fetched without start_date, derive range from messages for grouping
    if start_date is None:
        min_d = min(
            (
                d
                for m in all_messages
                for d in [_ts_to_date(m.get("ts"))]
                if d is not None
            ),
            default=None,
        )
        if min_d is None:
            return success_count, error_count
        start_date = min_d

    messages_by_day = _messages_by_day(all_messages, start_date, end_date)

    # Step 3: for each day with messages, write workspace; merge into raw; process → remove workspace
    d = start_date
    while d <= end_date:
        messages = messages_by_day.get(d, [])
        if not messages:
            d += timedelta(days=1)
            continue

        date_str = d.strftime("%Y-%m-%d")
        workspace_path = get_message_json_path(team_slug, channel_slug, date_str)
        raw_path = get_raw_message_json_path(team_slug, channel_slug, date_str)

        # Raw: merge with existing file if present (same ts → update, new ts → add)
        existing_list: list[dict] = []
        if raw_path.exists():
            try:
                data = json.loads(raw_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    existing_list = data
            except (json.JSONDecodeError, OSError):
                logger.debug("Could not load existing raw %s for merge", raw_path)
        merged_raw = _merge_messages_by_ts(existing_list, messages)
        raw_payload = json.dumps(merged_raw, indent=2, default=str)

        workspace_payload = json.dumps(messages, indent=2, default=str)
        try:
            workspace_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            workspace_path.write_text(workspace_payload, encoding="utf-8")
            raw_path.write_text(raw_payload, encoding="utf-8")
        except OSError:
            logger.exception(
                "Failed to write JSON for channel_id=%s date=%s", channel_id, date_str
            )
            d += timedelta(days=1)
            continue
        logger.debug(
            "Wrote %s and %s (%s messages, raw merged %s)",
            workspace_path,
            raw_path,
            len(messages),
            len(merged_raw),
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
