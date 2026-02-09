"""
Fetch Boost mailing list emails from the Mailman API.

Ported from old_project_files/fetch_boost_emails.py and adapted for Django
(logging, service layer, restart/resume logic via DB checks).
"""

import json
import logging
import time
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

# Default Boost mailing list API endpoints.
BOOST_LIST_URLS = [
    "https://lists.boost.org/archives/api/list/boost-announce@lists.boost.org/emails/",
    "https://lists.boost.org/archives/api/list/boost-users@lists.boost.org/emails/",
    "https://lists.boost.org/archives/api/list/boost@lists.boost.org/emails/",
]

# API pagination
PAGE_SIZE = 100
DEFAULT_RETRY_DELAY = 10  # seconds
MAX_RETRIES = 3
REQUEST_TIMEOUT = 30  # seconds


def _filter_by_date(
    results: list[dict[str, Any]],
    start_date: str,
    end_date: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Filter results by date range. Returns (filtered, should_stop).

    The API returns results in descending date order. If a result's date is
    before start_date, we stop early (no more results will match).
    """
    filtered: list[dict[str, Any]] = []
    stop = False
    for item in results:
        d = item.get("date")
        if start_date and d and d < start_date:
            stop = True
            break
        if end_date and d and d > end_date:
            continue
        filtered.append(item)
    return filtered, stop


def _fetch_page(url: str, page: int) -> Optional[dict[str, Any]]:
    """Fetch a single paginated API page with retry on HTTP 429."""
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
                logger.info(
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
            logger.error("HTTP error fetching page %d: %s", page, e)
            return None
        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            logger.error("Error fetching page %d: %s", page, e)
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

        if "results" not in data:
            # Single result (not paginated)
            return [data]

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


def fetch_email_content(url: str) -> Optional[list[dict[str, Any]]]:
    """Fetch the full email content from a detail URL."""
    return fetch_email_list(url)


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
        "parent_id": parent.split("/")[-2] if parent else "",
        "thread_id": thread.split("/")[-2] if thread else "",
        "subject": item.get("subject", ""),
        "content": item.get("content", ""),
        "list_name": source_url.split("/")[-3],
        "sent_at": item.get("date"),
        "sender_address": (
            sender.get("address", "").replace(" (a) ", "@") if sender else ""
        ),
        "sender_name": item.get("sender_name", ""),
    }


def fetch_all_emails(
    start_date: str = "",
    end_date: str = "",
    list_urls: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Fetch and format emails from all configured Boost mailing lists.

    Returns a list of formatted email dicts (may be empty on total failure).
    """
    urls = list_urls or BOOST_LIST_URLS
    all_emails: list[dict[str, Any]] = []

    for api_url in urls:
        list_name = api_url.split("/")[-3]
        logger.info("Fetching email index for %s ...", list_name)

        url_list = fetch_email_list(api_url, start_date, end_date)
        if not url_list or not isinstance(url_list, list):
            logger.warning("No email index data for %s", list_name)
            continue

        logger.info("  Found %d email entries for %s; fetching content...", len(url_list), list_name)

        for item in url_list:
            url = item.get("url")
            if not url:
                continue
            content_list = fetch_email_content(url)
            if content_list:
                for content_item in content_list:
                    formatted = format_email(content_item, api_url)
                    if formatted.get("msg_id"):
                        all_emails.append(formatted)
            else:
                logger.debug("No content for %s", url)

        logger.info("  Fetched %d emails total so far", len(all_emails))

    return all_emails
