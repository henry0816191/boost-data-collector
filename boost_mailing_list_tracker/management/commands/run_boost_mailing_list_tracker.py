"""
Management command: run_boost_mailing_list_tracker

Uses workspace like github_activity_tracker:
1. Process existing JSONs in workspace (load → persist to DB → remove file).
2. Fetch from API, save each as JSON, persist to DB, remove file.

See docs/Workflow.md and docs/Workspace.md.
"""

import json
import logging

from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime

from boost_mailing_list_tracker.fetcher import BOOST_LIST_URLS, fetch_all_emails
from boost_mailing_list_tracker.models import MailingListMessage
from boost_mailing_list_tracker.services import get_or_create_mailing_list_message
from boost_mailing_list_tracker.workspace import (
    get_message_json_path,
    iter_existing_message_jsons,
)
from cppa_user_tracker.services import (
    add_email,
    get_or_create_mailing_list_profile_by_email,
)

logger = logging.getLogger(__name__)


def _persist_email(email_data: dict) -> tuple[bool, bool]:
    """Persist one formatted email dict to DB. Returns (message_created, skipped).

    Sender is identified by email (sender_address); display_name is used only when creating.
    """
    msg_id = email_data.get("msg_id", "")
    if not msg_id:
        return False, True

    if MailingListMessage.objects.filter(msg_id=msg_id).exists():
        return False, True

    sender_name = email_data.get("sender_name", "") or ""
    sender_address = email_data.get("sender_address", "") or ""
    profile, _ = get_or_create_mailing_list_profile_by_email(
        email_address=sender_address,
        display_name=sender_name,
    )

    sent_at_str = email_data.get("sent_at")
    sent_at = parse_datetime(sent_at_str) if sent_at_str else None

    _, was_created = get_or_create_mailing_list_message(
        sender=profile,
        msg_id=msg_id,
        parent_id=email_data.get("parent_id", ""),
        thread_id=email_data.get("thread_id", ""),
        subject=email_data.get("subject", ""),
        content=email_data.get("content", ""),
        list_name=email_data.get("list_name", ""),
        sent_at=sent_at,
    )
    return was_created, False


def _process_existing_workspace_json(list_name: str) -> int:
    """Load each messages/*.json for this list, persist to DB, remove file. Returns count processed."""
    count = 0
    for path in iter_existing_message_jsons(list_name):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            _persist_email(data)
            path.unlink() 
            count += 1
        except Exception as e:
            logger.exception("Failed to process %s: %s", path, e)
    return count


class Command(BaseCommand):
    help = (
        "Fetch Boost mailing list emails and save to the database via workspace. "
        "Process existing workspace JSONs first, then fetch from API (write JSON → persist → remove)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            type=str,
            default="",
            help="Start date for fetching emails (ISO format, e.g. 2025-09-01). Default: fetch all.",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            default="",
            help="End date for fetching emails (ISO format, e.g. 2026-01-17). Default: fetch all.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and report counts but do not write to DB or workspace.",
        )

    def handle(self, *args, **options):
        start_date = options["start_date"]
        end_date = options["end_date"]
        dry_run = options["dry_run"]

        logger.info(
            "run_boost_mailing_list_tracker: starting (start_date=%s, end_date=%s, dry_run=%s)",
            start_date or "none",
            end_date or "none",
            dry_run,
        )

        list_names = [u.split("/")[-3] for u in BOOST_LIST_URLS]

        try:
            # Phase 1: process existing workspace JSONs
            if not dry_run:
                total_existing = 0
                for list_name in list_names:
                    n = _process_existing_workspace_json(list_name)
                    total_existing += n
                if total_existing:
                    self.stdout.write(
                        f"Processed {total_existing} existing message JSON(s) from workspace."
                    )
                    logger.info(
                        "run_boost_mailing_list_tracker: processed %s existing JSON(s)",
                        total_existing,
                    )

            # Phase 2: fetch from API, write JSON, persist to DB, remove file
            self.stdout.write("Fetching emails from Boost mailing list archives...")
            emails = fetch_all_emails(start_date=start_date, end_date=end_date)

            if not emails:
                self.stdout.write(self.style.WARNING("No emails fetched from API."))
                logger.info("run_boost_mailing_list_tracker: no emails fetched")
                return

            self.stdout.write(f"Fetched {len(emails)} emails from API.")

            if dry_run:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Dry run: would process {len(emails)} emails. No DB or workspace writes."
                    )
                )
                return

            created_count = 0
            skipped_count = 0

            for email_data in emails:
                msg_id = email_data.get("msg_id", "")
                list_name = email_data.get("list_name", "")
                if not msg_id:
                    skipped_count += 1
                    continue

                # Write to workspace (like github_activity_tracker: save JSON then persist then remove)
                json_path = get_message_json_path(list_name, msg_id)
                json_path.parent.mkdir(parents=True, exist_ok=True)
                json_path.write_text(
                    json.dumps(email_data, indent=2, default=str),
                    encoding="utf-8",
                )

                was_created, skipped = _persist_email(email_data)
                if was_created:
                    created_count += 1
                elif skipped:
                    skipped_count += 1

                json_path.unlink(missing_ok=True)

            self.stdout.write(
                self.style.SUCCESS(
                    f"Done: {created_count} created, {skipped_count} skipped (already existed or empty)."
                )
            )
            logger.info(
                "run_boost_mailing_list_tracker: finished; created=%d, skipped=%d",
                created_count,
                skipped_count,
            )

        except Exception as e:
            logger.exception("run_boost_mailing_list_tracker failed: %s", e)
            raise
