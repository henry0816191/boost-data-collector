"""
Convert GitHub issue JSON to Markdown (conversion only; no I/O).

Public API: issue_json_to_md(json_data) -> str
"""


def format_date(iso_str: str | None) -> str:
    """Format ISO date for display (e.g. 2020-01-20T09:05:53Z -> 2020-01-20 09:05:53 UTC)."""
    if not iso_str:
        return ""
    return iso_str.replace("T", " ").replace("Z", " UTC").rstrip()


def build_issue_md(data: dict) -> str:
    """Build markdown content for one issue from parsed JSON."""
    info = data.get("issue_info") or {}
    comments = data.get("comments") or []

    number = info.get("number", "?")
    title = (info.get("title") or "").strip()
    state_raw = (info.get("state") or "open").lower()
    state = "Closed" if state_raw == "closed" else "Open"

    user = info.get("user") or {}
    username = user.get("login") or "unknown"

    created_at = format_date(info.get("created_at"))
    updated_at = format_date(info.get("updated_at"))
    closed_at = format_date(info.get("closed_at"))

    issue_url = info.get("html_url") or info.get("url") or ""

    body = (info.get("body") or "").replace("\r\n", "\n").replace("\n", "  \n").strip()

    meta_lines = [
        f"Username: {username}",
        f"Created at: {created_at}",
        f"Updated at: {updated_at}",
    ]
    if state_raw == "closed" and closed_at:
        meta_lines.append(f"Closed at: {closed_at}")
    meta_lines.append(f"Url: {issue_url}")
    meta_block = "\n".join(f"> {m}  " for m in meta_lines)

    lines = [
        f"# #{number} - {title} [{state}]",
        "",
        meta_block,
        "",
        body,
        "",
    ]

    sorted_comments = sorted(
        comments,
        key=lambda c: c.get("created_at") or "",
    )
    for i, comment in enumerate(sorted_comments, start=1):
        lines.append("---")
        lines.append("")
        c_user = comment.get("user") or {}
        c_username = c_user.get("login") or "unknown"
        c_created = format_date(comment.get("created_at"))
        c_updated = format_date(comment.get("updated_at"))
        c_url = comment.get("html_url") or comment.get("url") or ""
        c_body = (
            (comment.get("body") or "")
            .replace("\r\n", "\n")
            .replace("\n", "  \n")
            .strip()
        )

        c_meta_lines = [
            f"Username: {c_username}",
            f"Created at: {c_created}",
        ]
        if c_created != c_updated and c_updated:
            c_meta_lines.append(f"Updated at: {c_updated}")
        c_meta_lines.append(f"Url: {c_url}")
        c_meta_block = "\n".join(f"> {m}  " for m in c_meta_lines)

        lines.append(f"## Comment {i}")
        lines.append("")
        lines.append(c_meta_block)
        lines.append("")
        lines.append(c_body)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def issue_json_to_md(json_data: dict) -> str:
    """
    Convert issue JSON to Markdown (conversion only; no I/O).

    Input: issue JSON dict with "issue_info" and optional "comments" (e.g. from
    raw GitHub issue JSON or saved issue file).
    Output: Markdown string.

    Args:
        json_data: Dict with keys issue_info (required) and comments (optional list).

    Returns:
        Markdown content for the issue.
    """
    return build_issue_md(json_data)
