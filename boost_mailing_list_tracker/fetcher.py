"""
Fetch Boost mailing list emails from the Mailman API.

Ported from old_project_files/fetch_boost_emails.py and adapted for Django
(logging, service layer, restart/resume logic via DB checks).

- If start_date is empty, uses the day after the latest sent_at in the database.
- Raw API responses are saved to workspace/.../raw/ and are not removed.
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from boost_mailing_list_tracker.models import MailingListName

logger = logging.getLogger(__name__)

# Boost mailing list API endpoints; derived from MailingListName enum (single source of truth).
BOOST_LIST_URLS = [
    f"https://lists.boost.org/archives/api/list/{m.value}/emails/"
    for m in MailingListName
]

# API pagination
PAGE_SIZE = 100
DEFAULT_RETRY_DELAY = 10  # seconds
MAX_RETRIES = 3
REQUEST_TIMEOUT = 30  # seconds


def _parse_datetime(s: str) -> Optional[datetime]:
    """Parse ISO date/datetime string to datetime. Returns None if empty or invalid."""
    if not s or not str(s).strip():
        return None
    raw = str(s).strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _parse_start_bound(start_date: str) -> Optional[datetime]:
    """Parse start_date to datetime for range comparison."""
    return _parse_datetime(start_date)


def _parse_end_bound(end_date: str) -> Optional[datetime]:
    """Parse end_date to datetime; date-only strings are treated as end of that day."""
    dt = _parse_datetime(end_date)
    if dt is None:
        return None
    if "T" not in str(end_date).strip():
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return dt


def _filter_by_date(
    results: list[dict[str, Any]],
    start_date: str,
    end_date: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Filter results by date range. Returns (filtered, should_stop).

    The API returns results in descending date order. If a result's date is
    before start_date, we stop early (no more results will match).
    start_date and end_date are parsed once; date-only end_date is treated
    as end of that day (23:59:59.999999). Items with missing/invalid dates
    are skipped (and logged at debug).
    """
    start_dt = _parse_start_bound(start_date) if start_date else None
    end_dt = _parse_end_bound(end_date) if end_date else None

    filtered: list[dict[str, Any]] = []
    stop = False
    for item in results:
        d = item.get("date")
        if not d:
            logger.debug(
                "Skipping item with missing date: %s", item.get("message_id_hash")
            )
            continue
        item_dt = _parse_datetime(d)
        if item_dt is None:
            logger.debug(
                "Skipping item with invalid date %r: %s", d, item.get("message_id_hash")
            )
            continue
        if start_dt is not None and item_dt < start_dt:
            stop = True
            break
        if end_dt is not None and item_dt > end_dt:
            continue
        filtered.append(item)
    return filtered, stop


def _fetch_page(url: str, page: int = 1) -> Optional[dict[str, Any]]:
    """Fetch a single paginated API page with retry on HTTP 429.

    When url is a base endpoint (no query string), appends limit and offset.
    When url already contains '?' (e.g. API-provided \"next\" URL), use as-is.
    """
    if "?" in url:
        url_with_params = url
    else:
        url_with_params = f"{url}?limit={PAGE_SIZE}&offset={(page - 1) * PAGE_SIZE}"

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url_with_params, timeout=REQUEST_TIMEOUT)

            if resp.status_code == 429:
                retry_after = DEFAULT_RETRY_DELAY
                if "Retry-After" in resp.headers:
                    try:
                        retry_after = int(resp.headers["Retry-After"])
                    except (ValueError, TypeError):
                        pass
                else:
                    try:
                        body = resp.json()
                        ra = body.get("retry_after") or body.get("retry-after")
                        if ra:
                            retry_after = int(ra)
                    except (json.JSONDecodeError, ValueError, TypeError):
                        pass

                if attempt == MAX_RETRIES - 1:
                    logger.warning(
                        "Rate limited on page %d after %d retries; giving up",
                        page,
                        MAX_RETRIES,
                    )
                    return None
                logger.debug(
                    "Rate limited on page %d, waiting %ds (retry %d/%d)",
                    page,
                    retry_after,
                    attempt + 1,
                    MAX_RETRIES,
                )
                time.sleep(retry_after)
                continue

            resp.raise_for_status()
            return resp.json()

        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                continue
            logger.exception("HTTP error fetching page %d", page)
            return None
        except (requests.exceptions.RequestException, json.JSONDecodeError):
            logger.exception("Error fetching page %d", page)
            return None

    return None


def fetch_email_list(
    api_url: str,
    start_date: str = "",
    end_date: str = "",
) -> Optional[list[dict[str, Any]]]:
    """Fetch the email index (list of email metadata) from a mailing list API endpoint.

    Handles pagination and date filtering. Returns list of email items or None on error.
    """
    results: list[dict[str, Any]] = []
    url = api_url
    page = 1

    while url:
        data = _fetch_page(url, page)
        if data is None:
            return None

        filtered, stop = _filter_by_date(
            data.get("results", []),
            start_date,
            end_date,
        )
        results.extend(filtered)

        if stop:
            break

        url = data.get("next")
        if url:
            page += 1

    return results if results else None


def _path_tail(value: Any) -> str:
    """Extract final path segment from a URL or plain id; safe for missing/invalid."""
    if not value:
        return ""
    s = str(value).strip().rstrip("/")
    return s.split("/")[-1] if s else ""


def format_email(item: dict[str, Any], source_url: str) -> dict[str, Any]:
    """Format a raw API email item into a dict matching our model fields.

    Returns dict with keys: msg_id, parent_id, thread_id, subject, content,
    list_name, sent_at, sender_address, sender_name.
    """
    parent = item.get("parent")
    thread = item.get("thread")
    sender = item.get("sender")

    return {
        "msg_id": item.get("message_id_hash", ""),
        "parent_id": _path_tail(parent),
        "thread_id": _path_tail(thread),
        "subject": item.get("subject", ""),
        "content": item.get("content", ""),
        "list_name": source_url.split("/")[-3],
        "sent_at": item.get("date"),
        "sender_address": (
            sender.get("address", "").replace(" (a) ", "@") if sender else ""
        ),
        "sender_name": item.get("sender_name", ""),
    }


def _get_start_date_from_db() -> str:
    """Return start_date as ISO 8601 UTC (e.g. 2025-11-13T05:25:55Z): the latest sent_at in the DB. Empty if no messages."""
    from django.db.models import Max
    from django.utils import timezone

    from boost_mailing_list_tracker.models import MailingListMessage

    result = MailingListMessage.objects.aggregate(Max("sent_at"))
    max_sent = result.get("sent_at__max")
    if max_sent is None:
        return ""
    if max_sent.tzinfo is not None:
        max_sent = max_sent.astimezone(timezone.utc)
    return max_sent.strftime("%Y-%m-%dT%H:%M:%SZ")


def _save_raw_email(list_name: str, raw_item: dict[str, Any], msg_id: str) -> None:
    """Save raw API response to workspace/.../raw/<msg_id>.json. These files are not removed."""
    from boost_mailing_list_tracker.workspace import get_raw_json_path

    path = get_raw_json_path(list_name, msg_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw_item, indent=2, default=str), encoding="utf-8")


def fetch_all_emails(
    start_date: str = "",
    end_date: str = "",
    list_urls: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Fetch and format emails from all configured Boost mailing lists.

    - If start_date is null or empty, uses the day after the latest sent_at in the database.
    - Raw scraped data is saved to workspace/raw/boost_mailing_list_tracker/<list_name>/
      before formatting; raw files are kept (not removed).

    Returns a list of formatted email dicts (may be empty on total failure).
    """
    urls = list_urls or BOOST_LIST_URLS
    all_emails: list[dict[str, Any]] = []

    # Use last date from DB when start_date not provided
    if not (start_date and start_date.strip()):
        start_date = _get_start_date_from_db()
        if start_date:
            logger.info("Using start_date from DB (latest sent_at): %s", start_date)
        else:
            start_date = ""

    for api_url in urls:
        list_name = api_url.split("/")[-3]
        logger.info("Fetching email index for %s ...", list_name)

        url_list = fetch_email_list(api_url, start_date, end_date)
        if not url_list:
            logger.warning("No email index data for %s", list_name)
            continue

        logger.info(
            "  Found %d email entries for %s; fetching content...",
            len(url_list),
            list_name,
        )

        for item in url_list:
            url = item.get("url")
            if not url:
                continue
            content_item = _fetch_page(url)
            if content_item:
                msg_id = content_item.get("message_id_hash") or ""
                raw_id = msg_id or url.rstrip("/").split("/")[-1] or "unknown"
                _save_raw_email(list_name, content_item, raw_id)
                formatted = format_email(content_item, api_url)
                if formatted.get("msg_id"):
                    all_emails.append(formatted)
            else:
                logger.debug("No content for %s", url)

        logger.info("  Fetched %d emails total so far", len(all_emails))

    return all_emails
