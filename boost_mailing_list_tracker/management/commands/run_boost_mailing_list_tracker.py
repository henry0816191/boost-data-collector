"""
Management command: run_boost_mailing_list_tracker

Uses workspace like github_activity_tracker:
1. Process existing JSONs in workspace (load → persist to DB → remove file).
2. Fetch from API, save each as JSON, persist to DB, remove file.

See docs/Workflow.md and docs/Workspace.md.
"""

import json
import logging
import os

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime

from boost_mailing_list_tracker.email_formatter import format_email
from boost_mailing_list_tracker.fetcher import (
    BOOST_LIST_URLS,
    _get_start_date_from_db,
    fetch_all_emails,
)
from boost_mailing_list_tracker.models import MailingListMessage
from boost_mailing_list_tracker.preprocesser import preprocess_mailing_list_for_pinecone
from boost_mailing_list_tracker.services import get_or_create_mailing_list_message
from boost_mailing_list_tracker.workspace import (
    get_raw_json_path,
    get_message_json_path,
    iter_existing_message_jsons,
)
from cppa_user_tracker.services import get_or_create_mailing_list_profile

logger = logging.getLogger(__name__)
PINECONE_NAMESPACE_ENV_KEY = "BOOST_MAILING_LIST_PINECONE_NAMESPACE"


def _clean_text(value: object) -> str:
    """Return DB-safe text (PostgreSQL rejects NUL bytes in text fields)."""
    if value is None:
        return ""
    return str(value).replace("\x00", "")


def _run_pinecone_sync(app_id: str, namespace: str) -> None:
    """
    Trigger cppa-pinecone-sync command if available.
    """
    if not app_id:
        logger.warning("Pinecone sync skipped: --pinecone-app-id is empty.")
        return
    if not namespace:
        logger.warning(
            "Pinecone sync skipped: namespace is empty (set --pinecone-namespace or %s).",
            PINECONE_NAMESPACE_ENV_KEY,
        )
        return

    try:
        call_command(
            "run_cppa_pinecone_sync",
            app_id=app_id,
            namespace=namespace,
            preprocess_fn=preprocess_mailing_list_for_pinecone,
        )
        logger.info(
            "run_boost_mailing_list_tracker: pinecone sync completed (app_id=%s, namespace=%s)",
            app_id,
            namespace,
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning(
            "Pinecone sync skipped/failed (run_cppa_pinecone_sync unavailable or errored): %s",
            exc,
        )


def _persist_email(email_data: dict) -> tuple[bool, bool]:
    """Persist one formatted email dict to DB. Returns (message_created, skipped).

    Sender is identified by email (sender_address); display_name is used only when creating.
    Skips rows with missing/invalid sender_address or sent_at.
    """
    msg_id = _clean_text(email_data.get("msg_id", "")).strip()
    if not msg_id:
        return False, True

    if MailingListMessage.objects.filter(msg_id=msg_id).exists():
        return False, True

    list_name = _clean_text(email_data.get("list_name", "")).strip()
    sender_name = _clean_text(email_data.get("sender_name", "")).strip()
    sender_address = _clean_text(email_data.get("sender_address", "")).strip()

    display_name = sender_name or "Unknown Sender"
    if display_name == "Unknown Sender" and sender_address and "@" in sender_address:
        display_name = sender_address.split("@")[0] or display_name

    sent_at_str = _clean_text(email_data.get("sent_at", "")).strip()
    error_reason = None
    try:
        sent_at = parse_datetime(sent_at_str) if sent_at_str else None
    except (TypeError, ValueError):
        sent_at = None
        error_reason = "invalid sent_at"
    if sent_at_str and sent_at is None:
        error_reason = "invalid sent_at"

    if not sender_address:
        error_reason = "missing sender_address"

    try:
        profile, _ = get_or_create_mailing_list_profile(
            email=sender_address,
            display_name=display_name,
        )

        _, was_created = get_or_create_mailing_list_message(
            sender=profile,
            msg_id=msg_id,
            parent_id=_clean_text(email_data.get("parent_id", "")),
            thread_id=_clean_text(email_data.get("thread_id", "")),
            subject=_clean_text(email_data.get("subject", "")),
            content=_clean_text(email_data.get("content", "")),
            list_name=list_name,
            sent_at=sent_at,
        )
    except Exception as e:
        logger.exception(
            "Failed to persist message (msg_id=%s, list_name=%s): %s",
            msg_id,
            list_name,
            e,
        )
        return False, True
    if error_reason:
        logger.warning(
            "Incomplete email: msg_id=%s, list_name=%s, reason=%s",
            msg_id,
            list_name,
            error_reason,
        )
    return was_created, False


def _process_existing_workspace_json(list_name: str) -> tuple[int, int]:
    """Load each messages/*.json for this list, persist to DB, remove file. Returns (files_processed, messages_skipped)."""
    processed = 0
    skipped = 0
    for path in iter_existing_message_jsons(list_name):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            formatted_data = format_email(data)
            fail_this_file = False
            for formatted_email in formatted_data:
                try:
                    _persist_email(formatted_email)
                except Exception:
                    fail_this_file = True
                    logger.exception(
                        "Failed to persist message from %s (msg_id=%s, subject=%s)",
                        path,
                        formatted_email.get("msg_id", "?"),
                        formatted_email.get("subject", "?"),
                    )
                    skipped += 1
            if not fail_this_file:
                path.unlink()
            processed += 1
        except Exception as e:
            logger.exception("Failed to process %s: %s", path, e)
    if skipped:
        logger.info(
            "run_boost_mailing_list_tracker: skipped %d message(s) due to persist errors",
            skipped,
        )
    return processed, skipped


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
        parser.add_argument(
            "--pinecone-app-id",
            type=str,
            default="",
            help="App ID passed to run_cppa_pinecone_sync (usually provided by workflow).",
        )
        parser.add_argument(
            "--pinecone-namespace",
            type=str,
            default=os.getenv(PINECONE_NAMESPACE_ENV_KEY, ""),
            help=f"Pinecone namespace for sync. Default from env {PINECONE_NAMESPACE_ENV_KEY}.",
        )

    def handle(self, *args, **options):
        start_date = options["start_date"]
        end_date = options["end_date"]
        dry_run = options["dry_run"]
        pinecone_app_id = (options.get("pinecone_app_id") or "").strip()
        pinecone_namespace = (options.get("pinecone_namespace") or "").strip()

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
                total_skipped = 0
                for list_name in list_names:
                    processed, skipped = _process_existing_workspace_json(list_name)
                    total_existing += processed
                    total_skipped += skipped

                self.stdout.write(
                    f"Processed {total_existing} existing message JSON(s) from workspace. {total_skipped} skipped."
                )
                logger.info(
                    "run_boost_mailing_list_tracker: processed %s existing JSON(s)",
                    total_existing,
                )

            # Phase 2: fetch from API
            if not (start_date and start_date.strip()):
                start_date = _get_start_date_from_db()
                if start_date:
                    logger.info(
                        "run_boost_mailing_list_tracker: using start_date from DB (latest sent_at): %s",
                        start_date,
                    )

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

            # Phase 3: process new JSONs in workspace
            created_count = 0
            skipped_count = 0

            for email_data in emails:
                msg_id = email_data.get("msg_id", "")
                list_name = email_data.get("list_name", "")
                if not msg_id:
                    skipped_count += 1
                    continue

                json_path = get_message_json_path(list_name, msg_id)
                try:
                    # Provisional raw archive for Phase 3:
                    # workspace/raw/boost_mailing_list_tracker/<list_name>/<msg_id>.json
                    # Keep these files (do not delete).
                    raw_path = get_raw_json_path(list_name, msg_id)
                    raw_path.parent.mkdir(parents=True, exist_ok=True)
                    raw_path.write_text(
                        json.dumps(email_data, indent=2, default=str),
                        encoding="utf-8",
                    )

                    # Write to workspace (like github_activity_tracker: save JSON then persist then remove)
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
                except Exception as e:
                    skipped_count += 1
                    logger.warning(
                        "Skipping malformed email list_name=%s msg_id=%s: %s",
                        list_name,
                        msg_id,
                        e,
                    )

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
            # Phase 4: upsert to Pinecone as final processing.
            _run_pinecone_sync(
                app_id=pinecone_app_id,
                namespace=pinecone_namespace,
            )

        except Exception as e:
            logger.exception("run_boost_mailing_list_tracker failed: %s", e)
            raise
