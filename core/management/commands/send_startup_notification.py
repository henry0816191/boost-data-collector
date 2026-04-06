"""
Post deploy/startup status to Slack and Discord webhooks (DB, Celery beat schedule, workers).
Invoked after health checks via: DEPLOY_BRANCH=<branch> make notify
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from urllib import request
from urllib.error import URLError

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from celery.schedules import crontab, schedule as celery_interval_schedule

from config.celery import app as celery_app

logger = logging.getLogger(__name__)

BEAT_LINES_CAP = 25


def _crontab_field_to_sorted_ints(field):
    if field is None:
        return None
    if isinstance(field, int):
        return [field]
    if isinstance(field, (set, frozenset)):
        return sorted(field)
    if hasattr(field, "__iter__") and not isinstance(field, (str, bytes)):
        try:
            return sorted(int(x) for x in field)
        except (TypeError, ValueError):
            return None
    return None


def _crontab_is_universal_star(field):
    if field is None:
        return True
    s = str(field).strip()
    return s in ("*", "**", "None")


def describe_celery_schedule(sched) -> str:
    if isinstance(sched, celery_interval_schedule):
        run_every = getattr(sched, "run_every", None)
        if run_every is not None:
            minutes = int(run_every.total_seconds() // 60)
            return f"every {minutes} minutes"
        return repr(sched)
    if isinstance(sched, crontab):
        hours = _crontab_field_to_sorted_ints(sched.hour)
        minutes = _crontab_field_to_sorted_ints(sched.minute)
        parts = []
        if (
            hours is not None
            and minutes is not None
            and len(hours) == 1
            and len(minutes) == 1
        ):
            parts.append(f"{hours[0]:02d}:{minutes[0]:02d} UTC")
        else:
            parts.append(f"crontab hour={sched.hour!r} minute={sched.minute!r}")
        if not _crontab_is_universal_star(getattr(sched, "day_of_week", None)):
            parts.append(f"dow={sched.day_of_week!r}")
        if not _crontab_is_universal_star(getattr(sched, "day_of_month", None)):
            parts.append(f"dom={sched.day_of_month!r}")
        if not _crontab_is_universal_star(getattr(sched, "month_of_year", None)):
            parts.append(f"moy={sched.month_of_year!r}")
        return " ".join(parts)
    return repr(sched)


def collect_beat_lines(beat_schedule: dict) -> tuple[list[str], int]:
    lines = []
    total = len(beat_schedule)
    for name in sorted(beat_schedule.keys()):
        entry = beat_schedule[name]
        task = entry.get("task", "?")
        sch = entry.get("schedule")
        cadence = describe_celery_schedule(sch) if sch is not None else "?"
        lines.append(f"- `{name}` → `{task}` @ {cadence}")
    return lines, total


def post_discord(webhook_url: str, title: str, description: str) -> None:
    embed = {
        "title": title,
        "description": description[:4000],
        "color": 0x3498DB,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload = {"username": "Boost Data Collector", "embeds": [embed]}
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with request.urlopen(req, timeout=15) as resp:
        if resp.status not in (200, 204):
            logger.warning("Discord webhook returned status %s", resp.status)


def post_slack(webhook_url: str, title: str, text: str) -> None:
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": title, "emoji": True},
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": f"```{text[:2800]}```"}},
    ]
    payload = {
        "username": "Boost Data Collector",
        "blocks": blocks,
        "icon_emoji": ":white_check_mark:",
    }
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with request.urlopen(req, timeout=15) as resp:
        if resp.status != 200:
            logger.warning("Slack webhook returned status %s", resp.status)


class Command(BaseCommand):
    help = "Send startup/deploy notification to Slack and Discord webhooks."

    def handle(self, *args, **options):
        if not getattr(settings, "ENABLE_STARTUP_NOTIFICATIONS", True):
            logger.info(
                "Startup notifications disabled (ENABLE_STARTUP_NOTIFICATIONS)."
            )
            return

        discord_url = (getattr(settings, "DISCORD_WEBHOOK_URL", None) or "").strip()
        slack_url = (getattr(settings, "SLACK_WEBHOOK_URL", None) or "").strip()
        if not discord_url and not slack_url:
            logger.info(
                "No DISCORD_WEBHOOK_URL or SLACK_WEBHOOK_URL; skipping notification."
            )
            return

        notify_at = datetime.now(timezone.utc)
        branch = os.environ.get("DEPLOY_BRANCH", "").strip() or "unknown"

        db_line = "DB: error"
        try:
            connection.ensure_connection()
            tables = connection.introspection.table_names()
            db_line = f"DB: OK, {len(tables)} tables"
        except Exception as exc:
            db_line = f"DB: failed ({exc})"

        beat_schedule = dict(celery_app.conf.beat_schedule or {})
        beat_lines, beat_total = collect_beat_lines(beat_schedule)
        shown = beat_lines[:BEAT_LINES_CAP]
        beat_block = "\n".join(shown)
        if beat_total > len(shown):
            beat_block += f"\n… and {beat_total - len(shown)} more"

        worker_line = "Celery workers: unknown"
        try:
            insp = celery_app.control.inspect(timeout=5.0)
            pong = insp.ping() if insp else None
            n = len(pong) if pong else 0
            worker_line = f"Celery workers: {n} (ping)"
        except Exception as exc:
            worker_line = f"Celery workers: inspect failed ({exc})"

        text_body = (
            f"Time (UTC): {notify_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Branch: {branch}\n"
            f"{db_line}\n"
            f"{worker_line}\n"
            f"Celery beat entries: {beat_total}\n"
            f"{beat_block if beat_block else '(none)'}"
        )

        title = "Boost Data Collector — stack healthy"
        errors = []
        if discord_url:
            try:
                post_discord(discord_url, title, text_body)
            except URLError as e:
                errors.append(f"Discord: {e}")
            except Exception as e:
                errors.append(f"Discord: {e}")
        if slack_url:
            try:
                post_slack(slack_url, title, text_body)
            except URLError as e:
                errors.append(f"Slack: {e}")
            except Exception as e:
                errors.append(f"Slack: {e}")

        if errors:
            for err in errors:
                logger.error("%s", err)
            sys.exit(1)

        logger.info("Startup notification sent.")
