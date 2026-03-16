"""
Convert GitHub PR JSON to Markdown (conversion only; no I/O).

Public API: pr_json_to_md(json_data) -> str
"""

import re
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional


def format_datetime(dt_string: Optional[str]) -> str:
    """Format datetime string to UTC format."""
    if not dt_string:
        return "N/A"
    try:
        dt = datetime.strptime(dt_string, "%Y-%m-%dT%H:%M:%SZ")
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return dt_string


def _parse_diff_hunk_header(header_line: str) -> tuple:
    """Parse @@ -old_start,old_count +new_start,new_count @@. Returns (old_start, new_start)."""
    m = re.match(
        r"@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@",
        header_line.strip(),
    )
    if m:
        return (int(m.group(1)), int(m.group(3)))
    return (1, 1)


def get_last_n_lines(diff_hunk: str, n: int = 3) -> str:
    """Extract the last n lines from a diff hunk, with line numbers."""
    if not diff_hunk:
        return ""
    lines = diff_hunk.strip().split("\n")
    if not lines:
        return ""
    old_cur = new_cur = 1
    numbered_lines = []
    for line in lines:
        if line.startswith("@@"):
            old_cur, new_cur = _parse_diff_hunk_header(line)
            continue
        if not line:
            continue
        prefix = line[0] if line else " "
        rest = line[1:] if len(line) > 1 else ""
        if prefix == " ":
            num = new_cur
            old_cur += 1
            new_cur += 1
        elif prefix == "-":
            num = old_cur
            old_cur += 1
        else:
            num = new_cur
            new_cur += 1
        content = f"{prefix} {rest}" if prefix in "+-" else f"{prefix}{rest}"
        numbered_lines.append((num, content))
    last = numbered_lines[-n:] if len(numbered_lines) >= n else numbered_lines
    return "\n".join(f"{num:>4} |{content}" for num, content in last)


def build_comment_tree(comments: List[Dict]) -> tuple:
    """Build a tree structure for comments and their replies. Returns (replies_map, root_comments)."""
    replies_map = defaultdict(list)
    root_comments = []
    for comment in comments:
        reply_to_id = comment.get("in_reply_to_id")
        if reply_to_id:
            replies_map[reply_to_id].append(comment)
        else:
            root_comments.append(comment)
    return replies_map, root_comments


def _parse_plus_lines_with_numbers(diff_hunk: str) -> list:
    """Parse diff_hunk and return list of (line_number, content) for + lines."""
    lines = diff_hunk.strip().split("\n")
    if not lines:
        return []
    old_cur = new_cur = 1
    result = []
    for line in lines:
        if line.startswith("@@"):
            old_cur, new_cur = _parse_diff_hunk_header(line)
            continue
        if not line:
            continue
        prefix = line[0] if line else " "
        rest = line[1:] if len(line) > 1 else ""
        if prefix == " ":
            old_cur += 1
            new_cur += 1
        elif prefix == "-":
            old_cur += 1
        else:
            result.append((new_cur, rest))
            new_cur += 1
    return result


def _transform_suggestion_to_diff(
    body: str, diff_hunk: str, original_line: Optional[int] = None
) -> str:
    """Convert ```suggestion blocks to GitHub-style diff (- old / + new)."""
    body = body or ""
    if "```suggestion" not in body:
        return body
    plus_lines = _parse_plus_lines_with_numbers(diff_hunk) if diff_hunk else []
    line_num_to_content = {num: content for num, content in plus_lines}
    fallback_old_lines = [c for _, c in plus_lines]
    pattern = re.compile(
        r"```suggestion\r?\n(.*?)\r?\n```",
        re.DOTALL,
    )

    def replace_suggestion(match):
        suggested_content = (match.group(1) or "").replace("\r", "").strip("\r\n")
        suggested_lines = suggested_content.split("\n")
        n = len(suggested_lines)
        old_lines = []
        if n > 0 and original_line is not None and line_num_to_content:
            for i in range(n):
                ln = original_line + i
                old_lines.append(line_num_to_content.get(ln, ""))
        elif fallback_old_lines and n > 0:
            old_lines = (
                fallback_old_lines[-n:]
                if len(fallback_old_lines) >= n
                else fallback_old_lines
            )
            while len(old_lines) < n:
                old_lines.insert(0, "")
        if old_lines:
            diff_lines = []
            for i in range(n):
                old_line = old_lines[i] if i < len(old_lines) else ""
                new_line = suggested_lines[i] if i < len(suggested_lines) else ""
                if old_line:
                    diff_lines.append("-" + old_line)
                if new_line:
                    diff_lines.append("+" + new_line)
            return "```diff\n" + "\n".join(diff_lines) + "\n```"
        return "```diff\n" + "\n".join("+" + line for line in suggested_lines) + "\n```"

    return pattern.sub(replace_suggestion, body)


def format_comment_with_replies(
    comment: Dict, replies_map: Dict, indent: int = 0
) -> str:
    """Format a comment and its replies recursively."""
    indent_str = "    " * indent
    output = []
    username = (comment.get("user") or {}).get("login", "Unknown")
    created_at = format_datetime(comment.get("created_at"))
    updated_at = comment.get("updated_at")
    body = (comment.get("body") or "").strip()
    url = comment.get("html_url", "")
    output.append(f"{indent_str}> Username: {username}  ")
    output.append(f"{indent_str}> Created_at: {created_at}  ")
    if updated_at and updated_at != comment.get("created_at"):
        output.append(f"{indent_str}> Updated_at: {format_datetime(updated_at)}  ")
    if url:
        output.append(f"{indent_str}> Url: {url}  ")
    original_line = comment.get("original_line") or comment.get("line")
    body = _transform_suggestion_to_diff(
        body, comment.get("diff_hunk", ""), original_line
    )
    body = body.replace("\r", "").replace("\n", "  \n")
    output.append("")
    output.append(f"{indent_str}{body}")
    output.append("")
    comment_id = comment.get("id")
    if comment_id and comment_id in replies_map:
        for reply in replies_map[comment_id]:
            output.append(format_comment_with_replies(reply, replies_map, indent + 1))
    return "\n".join(output)


def format_review_comments(review_comments: List[Dict], replies_map: Dict) -> str:
    """Format review comments grouped by file."""
    if not review_comments:
        return ""
    output = []
    comments_by_file = defaultdict(list)
    for comment in review_comments:
        if not comment.get("in_reply_to_id"):
            path = comment.get("path", "Unknown file")
            comments_by_file[path].append(comment)
    for file_path, comments in comments_by_file.items():
        for i, comment in enumerate(comments):
            if i > 0:
                output.append("---")
                output.append("")
            resolved = comment.get("resolved") or comment.get("resolution")
            resolved_suffix = " [Resolved]" if resolved else ""
            output.append(f"📁 {file_path}{resolved_suffix}")
            output.append("")

            diff_hunk = comment.get("diff_hunk", "")
            if diff_hunk:
                last_lines = get_last_n_lines(diff_hunk, 3)
                if last_lines:
                    output.append("```diff")
                    output.append(last_lines)
                    output.append("```")
                    output.append("")
            output.append(format_comment_with_replies(comment, replies_map, 0))
        output.append("")
    return "\n".join(output)


def convert_pr_to_markdown(pr_data: Dict) -> str:
    """Convert PR JSON data to markdown format."""
    pr_info = pr_data.get("pr_info", {})
    reviews = pr_data.get("reviews", [])
    comments = pr_data.get("comments", [])

    pr_number = pr_info.get("number", "N/A")
    title = pr_info.get("title") or "No Title"
    state = pr_info.get("state", "unknown")
    merged = pr_info.get("merged", False)
    username = (pr_info.get("user") or {}).get("login", "Unknown")
    created_at = format_datetime(pr_info.get("created_at"))
    updated_at = format_datetime(pr_info.get("updated_at"))
    merged_at = format_datetime(pr_info.get("merged_at"))
    closed_at = format_datetime(pr_info.get("closed_at"))
    url = pr_info.get("html_url", "")
    body = (pr_info.get("body") or "").replace("\r", "").replace("\n", "  \n").strip()

    if merged:
        state_display = "Merged"
    else:
        state_display = state.capitalize() if isinstance(state, str) else state

    output = []
    output.append(f"# #{pr_number} {title} [{state_display}]")
    output.append("")
    output.append(f"> Username: {username}  ")
    output.append(f"> Created at: {created_at}  ")
    output.append(f"> Updated at: {updated_at}  ")
    if merged_at != "N/A":
        output.append(f"> Merged at: {merged_at}  ")
    if closed_at != "N/A":
        output.append(f"> Closed at: {closed_at}  ")
    output.append(f"> Url: {url}  ")
    output.append("")
    output.append(body)
    output.append("")
    output.append("---")
    output.append("")

    all_items = []
    for comment in comments:
        all_items.append(
            {
                "type": "comment",
                "data": comment,
                "created_at": comment.get("created_at") or "",
            }
        )
    for review in reviews:
        all_items.append(
            {
                "type": "review",
                "data": review,
                "created_at": review.get("submitted_at") or "",
            }
        )
    all_items.sort(key=lambda x: x["created_at"] or "")

    all_review_comments = pr_data.get("comments", [])
    review_comments_list = (
        [c for c in all_review_comments if c.get("pull_request_review_id")]
        if isinstance(all_review_comments, list)
        else []
    )
    replies_map, _ = build_comment_tree(review_comments_list)
    item_counter = 1

    for item in all_items:
        item_type = item["type"]
        data = item["data"]

        if item_type == "comment":
            if not data.get("pull_request_review_id"):
                output.append(f"## Comment {item_counter}")
                output.append("")
                username = (data.get("user") or {}).get("login", "Unknown")
                created_at = format_datetime(data.get("created_at"))
                updated_at = data.get("updated_at")
                body = (
                    (data.get("body") or "")
                    .strip()
                    .replace("\r", "")
                    .replace("\n", "  \n")
                )
                url = data.get("html_url", "")
                output.append(f"> Username: {username}  ")
                output.append(f"> Created_at: {created_at}  ")
                if updated_at and updated_at != data.get("created_at"):
                    output.append(f"> Updated_at: {format_datetime(updated_at)}  ")
                output.append(f"> Url: {url}  ")
                output.append("")
                output.append(body)
                output.append("")
                output.append("---")
                output.append("")
                item_counter += 1

        elif item_type == "review":
            username = (data.get("user") or {}).get("login", "Unknown")
            submitted_at = format_datetime(data.get("submitted_at"))
            state = data.get("state", "COMMENTED")
            state_tag = {
                "APPROVED": "[Approved]",
                "CHANGES_REQUESTED": "[Changes requested]",
                "COMMENTED": "[Commented]",
            }.get(
                state.upper() if isinstance(state, str) else state,
                "[Commented]",
            )
            body = (
                (data.get("body") or "").strip().replace("\r", "").replace("\n", "  \n")
            )
            url = data.get("html_url", "")
            review_id = data.get("id")
            review_comments = [
                c
                for c in review_comments_list
                if c.get("pull_request_review_id") == review_id
                and not c.get("in_reply_to_id")
            ]
            if not body and not review_comments:
                continue
            output.append(f"## Review {item_counter} {state_tag}")
            output.append("")
            output.append(f"> Username: {username}  ")
            output.append(f"> Created_at: {submitted_at}  ")
            output.append(f"> State: {state}  ")
            if url:
                output.append(f"> Url: {url}  ")
            output.append("")
            if body:
                output.append(body)
                output.append("")
            if review_comments:
                output.append(format_review_comments(review_comments, replies_map))
            output.append("---")
            output.append("")
            item_counter += 1

    return "\n".join(output)


def pr_json_to_md(json_data: Dict) -> str:
    """
    Convert PR JSON to Markdown (conversion only; no I/O).

    Input: PR JSON dict with "pr_info", optional "reviews" and "comments"
    (e.g. from raw GitHub PR JSON or saved PR file).
    Output: Markdown string.

    Args:
        json_data: Dict with keys pr_info (required), reviews and comments (optional).

    Returns:
        Markdown content for the PR.
    """
    return convert_pr_to_markdown(json_data)
