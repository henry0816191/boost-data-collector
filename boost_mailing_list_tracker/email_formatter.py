"""
Normalize workspace mailing-list JSON payloads into DB-ready email records.

Supported input shapes:
1) A list of already-formatted records (contains msg_id/sent_at/list_name, etc).
2) A list of thread email records (contains message_id, thread_url, parent, from, date, ...).
3) A thread object with {"thread_info": {...}, "messages": [...]}.

Output shape per record:
{
    "msg_id": str,
    "parent_id": str,
    "thread_id": str,
    "subject": str,
    "content": str,
    "list_name": str,
    "sent_at": str | None,   # ISO 8601 when possible
    "sender_address": str,
    "sender_name": str,
}
"""

from __future__ import annotations

import re
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any


def _to_text(value: Any) -> str:
    return (
        value if isinstance(value, str) else (str(value) if value is not None else "")
    )


def _extract_url_tail_id(value: Any) -> str:
    text = _to_text(value).strip().rstrip("/")
    if not text:
        return ""
    if "/" in text:
        return text.split("/")[-1]
    return text


def _extract_list_name(*sources: Any) -> str:
    pattern = re.compile(r"/list/([^/]+)/")
    for source in sources:
        text = _to_text(source).strip()
        if not text:
            continue
        # URL style: .../list/<list_name>/...
        match = pattern.search(text)
        if match:
            return match.group(1)
        # Direct list address style.
        if "@lists.boost.org" in text:
            candidates = re.findall(r"[A-Za-z0-9._%+\-]+@lists\.boost\.org", text)
            if candidates:
                return candidates[0]
    return ""


def _deobfuscate_address(addr: str) -> str:
    """Normalize address: lowercase, replace common obfuscations with '@', strip."""
    if not addr:
        return ""
    s = addr.lower().strip()
    for pattern in [" (a) ", " [at] ", " [at]", "[at] ", " at ", " AT "]:
        s = s.replace(pattern, "@")
    s = s.replace("[at]", "@").replace("(at)", "@")
    return s.strip(" \t.,;()[]")


def _extract_sender(raw: dict[str, Any]) -> tuple[str, str]:
    sender_address = _to_text(raw.get("sender_address")).strip()
    sender_name = _to_text(raw.get("sender_name")).strip()

    # Prefer nested "sender" dict when present (e.g. API payloads used by fetcher).
    sender_obj = raw.get("sender")
    if isinstance(sender_obj, dict):
        addr = _to_text(
            sender_obj.get("address") or sender_obj.get("email") or ""
        ).strip()
        addr = _deobfuscate_address(addr) if addr else ""
        name = _to_text(
            sender_obj.get("name")
            or sender_obj.get("sender_name")
            or sender_obj.get("display_name")
            or ""
        ).strip()
        if addr:
            sender_address = sender_address or addr
        if name:
            sender_name = sender_name or name

    sender_address = _deobfuscate_address(sender_address) if sender_address else ""
    if sender_address and sender_name:
        return sender_address, sender_name

    # "from" examples:
    # - Marc Perso <marc.viala@sfr.fr>
    # - "Lifshitz, Yair" <yair.lifshitz@intel.com>
    raw_from = _to_text(raw.get("from")).strip()
    if raw_from:
        match = re.search(r"<([^>]+)>", raw_from)
        if match and not sender_address:
            sender_address = match.group(1).strip()
        if not sender_name:
            sender_name = raw_from.split("<", 1)[0].strip().strip('"').strip()

    sender_address = _deobfuscate_address(sender_address) if sender_address else ""
    return sender_address, sender_name


def _normalize_sent_at(raw: dict[str, Any]) -> str | None:
    sent_at = _to_text(raw.get("sent_at")).strip()
    if sent_at:
        return sent_at

    date_value = _to_text(raw.get("date")).strip()
    if not date_value:
        return None

    # Try RFC2822 first (e.g. "Sat, 03 Apr 2010 18:32:00 +0200").
    try:
        parsed = parsedate_to_datetime(date_value)
        if parsed.tzinfo is None:
            return parsed.isoformat()
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError):
        # Already ISO-ish or unknown; keep original so downstream can try parse_datetime.
        return date_value


def _normalize_one(
    raw: dict[str, Any], thread_info: dict[str, Any] | None = None
) -> dict[str, Any]:
    thread_info = thread_info or {}

    msg_id = (
        _to_text(raw.get("msg_id")).strip()
        or _to_text(raw.get("message_id_hash")).strip()
        or _extract_url_tail_id(raw.get("url"))
        or _to_text(raw.get("message_id")).strip()
    )
    parent_id = _to_text(raw.get("parent_id")).strip() or _extract_url_tail_id(
        raw.get("parent")
    )
    thread_id = (
        _to_text(raw.get("thread_id")).strip()
        or _extract_url_tail_id(raw.get("thread"))
        or _extract_url_tail_id(raw.get("thread_url"))
        or _to_text(thread_info.get("thread_id")).strip()
    )
    list_name = _to_text(raw.get("list_name")).strip() or _extract_list_name(
        raw.get("url"),
        raw.get("thread_url"),
        thread_info.get("url"),
        thread_info.get("emails_url"),
        raw.get("to"),
    )
    sender_address, sender_name = _extract_sender(raw)

    return {
        "msg_id": msg_id,
        "parent_id": parent_id,
        "thread_id": thread_id,
        "subject": _to_text(raw.get("subject")).strip(),
        "content": _to_text(raw.get("content")),
        "list_name": list_name,
        "sent_at": _normalize_sent_at(raw),
        "sender_address": sender_address,
        "sender_name": sender_name,
    }


def format_email(payload: Any) -> list[dict[str, Any]]:
    """
    Convert workspace payload into a list of normalized message dictionaries.
    """
    if isinstance(payload, list):
        return [_normalize_one(item) for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        messages = payload.get("messages")
        if isinstance(messages, list):
            thread_info = payload.get("thread_info")
            if not isinstance(thread_info, dict):
                thread_info = {}
            return [
                _normalize_one(item, thread_info=thread_info)
                for item in messages
                if isinstance(item, dict)
            ]

        # Single-message dict fallback.
        return [_normalize_one(payload)]

    return []
