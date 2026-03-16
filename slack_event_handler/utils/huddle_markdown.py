"""
Huddle Markdown: orchestration for Slack huddle -> markdown.
Reads HTML/JSON, fetches Slack channel/user info, then uses operations.md_ops for transcript MD.
"""

import json
import logging
import re

from operations.md_ops import html_to_markdown
from operations.md_ops.transcript import (
    generate_transcript_from_json,
    parse_html_summary,
    replace_channel_ids_with_names,
    replace_user_ids_with_usernames,
    write_huddle_transcript_md,
)

from operations.slack_ops import SlackFetcher

logger = logging.getLogger(__name__)


def generate_huddle_markdown(
    html_file_path,
    result_json_path,
    output_dir=".",
    bot_token=None,
):
    """Generate markdown file from huddle HTML and JSON transcript."""
    try:
        with open(html_file_path, "r", encoding="utf-8") as f:
            html_content = f.read()
    except Exception as e:
        logger.error("Error reading HTML file: %s", e)
        return None
    try:
        with open(result_json_path, "r", encoding="utf-8") as f:
            result_json = json.load(f)
    except Exception as e:
        logger.error("Error reading JSON file: %s", e)
        return None

    html_data = parse_html_summary(html_content)
    try:
        fetcher = SlackFetcher(bot_token)
    except ValueError as e:
        logger.error("Error: %s", e)
        return None

    channel_name = fetcher.get_channel_info(html_data["channel_id"])
    user_info_map = {}
    for user_id in html_data["attendee_ids"]:
        user_info_map[user_id] = fetcher.get_user_info(user_id)
    for user_id in re.findall(r"@(U[A-Z0-9]+)", html_content):
        if user_id not in user_info_map:
            user_info_map[user_id] = fetcher.get_user_info(user_id)

    transcript = generate_transcript_from_json(result_json)
    for entry in transcript:
        if entry.get("user_id") and entry["user_id"] not in user_info_map:
            user_info_map[entry["user_id"]] = fetcher.get_user_info(entry["user_id"])

    summary_markdown = html_to_markdown(html_content)
    summary_markdown = replace_user_ids_with_usernames(summary_markdown, user_info_map)
    summary_markdown = replace_channel_ids_with_names(
        summary_markdown, html_data.get("channel_id"), channel_name
    )
    summary_markdown = re.sub(r"^## ", "#### ", summary_markdown, flags=re.MULTILINE)
    summary_markdown = re.sub(r"^# ", "### ", summary_markdown, flags=re.MULTILINE)

    result_path = write_huddle_transcript_md(
        output_dir,
        html_content=html_content,
        result_json=result_json,
        channel_name=channel_name,
        user_info_map=user_info_map,
        summary_markdown=summary_markdown,
    )
    return str(result_path) if result_path else None
