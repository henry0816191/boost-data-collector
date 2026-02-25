"""
Transcript markdown: parse huddle HTML/JSON and write transcript .md files.
Used by cppa_slack_transcript_tracker; caller provides channel_name and user_info_map (from Slack).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

import pytz

from operations.md_ops._write import write_markdown

logger = logging.getLogger(__name__)
PST = pytz.timezone("America/Los_Angeles")


def parse_datetime_range(datetime_str: str, date_str: str | None = None) -> str:
    """Parse datetime string and convert to PST formatted range."""
    try:
        tz_match = re.search(r"\s+([A-Z]{2,4})\s*$", datetime_str)
        input_tz_str = tz_match.group(1) if tz_match else None
        tz_map = {
            "PST": "America/Los_Angeles",
            "PDT": "America/Los_Angeles",
            "EST": "America/New_York",
            "EDT": "America/New_York",
            "CST": "America/Chicago",
            "CDT": "America/Chicago",
            "MST": "America/Denver",
            "MDT": "America/Denver",
            "UTC": "UTC",
            "GMT": "UTC",
        }
        if input_tz_str and input_tz_str.upper() in tz_map:
            source_tz = pytz.timezone(tz_map[input_tz_str.upper()])
        else:
            source_tz = PST
        time_match = re.search(
            r"(\d+:\d+:\d+\s+[AP]M)\s*-\s*(\d+:\d+:\d+\s+[AP]M)", datetime_str
        )
        if not time_match:
            return datetime_str
        start_time_str, end_time_str = time_match.group(1), time_match.group(2)
        if date_str:
            try:
                parsed_date = (
                    datetime.strptime(date_str, "%m/%d/%y")
                    if len(date_str.split("/")[-1]) == 2
                    else datetime.strptime(date_str, "%m/%d/%Y")
                )
                date_naive = parsed_date
            except ValueError:
                date_naive = datetime.now(PST).replace(tzinfo=None)
        else:
            date_naive = datetime.now(PST).replace(tzinfo=None)
        try:
            start_dt_naive = datetime.strptime(
                f"{date_naive.strftime('%Y-%m-%d')} {start_time_str}",
                "%Y-%m-%d %I:%M:%S %p",
            )
            end_dt_naive = datetime.strptime(
                f"{date_naive.strftime('%Y-%m-%d')} {end_time_str}",
                "%Y-%m-%d %I:%M:%S %p",
            )
            start_dt_source = source_tz.localize(start_dt_naive)
            end_dt_source = source_tz.localize(end_dt_naive)
            start_dt = start_dt_source.astimezone(PST)
            end_dt = end_dt_source.astimezone(PST)
            if end_dt < start_dt:
                from datetime import timedelta

                end_dt_naive_next = end_dt_naive + timedelta(days=1)
                end_dt_source = source_tz.localize(end_dt_naive_next)
                end_dt = end_dt_source.astimezone(PST)
            return f"{start_dt.strftime('%Y-%m-%d_%H-%M')} PST - {end_dt.strftime('%Y-%m-%d_%H-%M')} PST"
        except ValueError:
            return datetime_str
    except Exception:
        return datetime_str


def parse_html_summary(html_content: str) -> dict:
    """Parse HTML content from Slack huddle summary file."""
    html_data = {
        "channel_id": None,
        "attendee_ids": [],
        "datetime": "",
        "datetime_formatted": "",
    }
    try:
        channel_match = re.search(r"#(C[A-Z0-9]+)", html_content)
        if channel_match:
            html_data["channel_id"] = channel_match.group(1)
        date_match = re.search(r"Huddle notes:\s*(\d+/\d+/\d+)", html_content)
        date_str = date_match.group(1) if date_match else None
        datetime_match = re.search(r"<b>([^<]+)</b>", html_content)
        if datetime_match:
            datetime_str = datetime_match.group(1)
            html_data["datetime"] = datetime_str
            html_data["datetime_formatted"] = parse_datetime_range(
                datetime_str, date_str
            )
        attendees_match = re.search(
            r"<h2[^>]*>.*?Attendees.*?</h2>.*?<p[^>]*>(.*?)</p>",
            html_content,
            re.DOTALL | re.IGNORECASE,
        )
        if attendees_match:
            attendees_section = attendees_match.group(1)
            attendee_matches = re.findall(r"@(U[A-Z0-9]+)", attendees_section)
            seen: set[str] = set()
            html_data["attendee_ids"] = [
                x for x in attendee_matches if x not in seen and not seen.add(x)
            ]
        else:
            attendee_matches = re.findall(r"@(U[A-Z0-9]+)", html_content)
            seen = set()
            html_data["attendee_ids"] = [
                x for x in attendee_matches if x not in seen and not seen.add(x)
            ]
    except Exception as e:
        logger.debug("Error parsing HTML: %s", e)
    return html_data


def replace_user_ids_with_usernames(markdown_content: str, user_info_map: dict) -> str:
    """Replace user IDs with usernames in markdown."""

    def replace_user_id(match: re.Match) -> str:
        user_id = match.group(1)
        if user_id in user_info_map:
            u = user_info_map[user_id]
            username = (
                u.get("display_name") or u.get("real_name") or u.get("name", user_id)
            )
            return f"**@{username}**"
        return match.group(0)

    return re.sub(r"@(U[A-Z0-9]+)", replace_user_id, markdown_content)


def replace_channel_ids_with_names(
    markdown_content: str, channel_id: str | None, channel_name: str
) -> str:
    """Replace channel IDs with channel names in markdown."""
    if channel_id and channel_name:
        markdown_content = re.sub(
            rf"#({re.escape(channel_id)})", f"#{channel_name}", markdown_content
        )
    return markdown_content


def generate_transcript_from_json(result_json: dict) -> list[dict]:
    """Generate transcript entries from Slack huddle result JSON."""
    transcript = []
    try:
        file_data = result_json.get("file", {})
        transcription = file_data.get("huddle_transcription", {})
        blocks = transcription.get("blocks", [])
        if isinstance(blocks, dict):
            blocks = blocks.get("elements", [])
        if not isinstance(blocks, list):
            blocks = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            elements = block.get("elements", [])
            for element in elements:
                if element.get("type") == "rich_text_section":
                    section_elements = element.get("elements", [])
                    user_id = None
                    time_str = ""
                    content_parts = []
                    for sub_elem in section_elements:
                        if sub_elem.get("type") == "user":
                            user_id = sub_elem.get("user_id")
                        elif sub_elem.get("type") == "text":
                            text = sub_elem.get("text", "")
                            time_m = re.match(r"^\s*\[(\d+:\d+)\]:\s*$", text)
                            if time_m:
                                time_str = time_m.group(1)
                            else:
                                content_parts.append(text)
                    if user_id and (time_str or content_parts):
                        transcript.append(
                            {
                                "user_id": user_id,
                                "time": time_str,
                                "content": "".join(content_parts).strip(),
                            }
                        )
    except Exception as e:
        logger.debug("Error parsing transcript: %s", e)
    return transcript


def write_huddle_transcript_md(
    output_dir: str | Path,
    *,
    html_content: str,
    result_json: dict,
    channel_name: str,
    user_info_map: dict,
    summary_markdown: str,
) -> Path | None:
    """
    Build and write a huddle transcript markdown file.

    Caller must provide:
    - html_content: raw HTML from huddle summary
    - result_json: Slack transcript API response (file with huddle_transcription)
    - channel_name: Slack channel name (from Slack API)
    - user_info_map: dict user_id -> {display_name, real_name, name}
    - summary_markdown: HTML converted to markdown, with @user/#channel replaced (caller does html_to_markdown + replace_*)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    html_data = parse_html_summary(html_content)
    transcript = generate_transcript_from_json(result_json)

    if html_data.get("datetime_formatted"):
        date_match = re.search(
            r"^(\d{4}-\d{2}-\d{2})_\d{2}-\d{2}", html_data["datetime_formatted"]
        )
        date_part = (
            date_match.group(1)
            if date_match
            else datetime.now(PST).strftime("%Y-%m-%d")
        )
        time_match = re.search(
            r"^\d{4}-\d{2}-\d{2}_(\d{2}-\d{2})", html_data["datetime_formatted"]
        )
        time_part = (
            time_match.group(1) if time_match else datetime.now(PST).strftime("%H-%M")
        )
        date_str = f"{date_part}_{time_part}"
    else:
        date_str = datetime.now(PST).strftime("%Y-%m-%d_%H-%M")

    usernames = []
    for user_id in html_data["attendee_ids"]:
        u = user_info_map.get(user_id, {})
        usernames.append(
            u.get("display_name") or u.get("real_name") or u.get("name", user_id)
        )
    username_str = "_".join(usernames[:5])
    if len(usernames) > 5:
        username_str += "_and_more"
    filename = f"{channel_name}_{date_str}_{username_str}.md"
    filename = re.sub(r'[<>:"/\\|?*]', "_", filename)
    filepath = output_dir / filename

    markdown_lines = []
    title_date = date_str.replace("_", " ")
    markdown_lines.append(f"# {channel_name} Huddle - {title_date}")
    markdown_lines.append("")
    if html_data.get("datetime_formatted"):
        markdown_lines.append(f"**datetime:** {html_data['datetime_formatted']}  ")
    else:
        original_datetime = html_data.get("datetime", "")
        if original_datetime:
            date_match = re.search(r"Huddle notes:\s*(\d+/\d+/\d+)", html_content)
            date_str_parse = date_match.group(1) if date_match else None
            markdown_lines.append(
                f"**datetime:** {parse_datetime_range(original_datetime, date_str_parse)}  "
            )
        else:
            markdown_lines.append(
                f"**datetime:** {datetime.now(PST).strftime('%Y-%m-%d_%H-%M')} PST  "
            )
    markdown_lines.append(f"**location:** #{channel_name} Slack channel  ")
    markdown_lines.append("**type:** HUDDLE  ")
    attendee_names = [
        user_info_map[uid].get("display_name")
        or user_info_map[uid].get("real_name")
        or user_info_map[uid].get("name", uid)
        for uid in html_data["attendee_ids"]
        if uid in user_info_map
    ]
    if not attendee_names:
        attendees_str = "Unknown"
    elif len(attendee_names) == 1:
        attendees_str = attendee_names[0]
    elif len(attendee_names) == 2:
        attendees_str = f"{attendee_names[0]} and {attendee_names[1]}"
    else:
        attendees_str = ", ".join(attendee_names[:-1]) + f", and {attendee_names[-1]}"
    markdown_lines.append(f"**attendees:** {attendees_str}  ")
    markdown_lines.append("")
    markdown_lines.append("## Slack AI Summary")
    markdown_lines.append("")
    if summary_markdown.strip():
        markdown_lines.append(summary_markdown.strip())
        markdown_lines.append("")
    markdown_lines.append("## Transcript")
    markdown_lines.append("")
    for entry in transcript:
        user_id = entry["user_id"]
        time_str = entry.get("time", "")
        content = entry.get("content", "")
        u = user_info_map.get(user_id, {})
        username = u.get("display_name") or u.get("real_name") or u.get("name", user_id)
        if time_str:
            markdown_lines.append(f"**@{username} [{time_str}]:** {content}  ")
        else:
            markdown_lines.append(f"**@{username}:** {content}  ")
    markdown_lines.append("")

    try:
        write_markdown(filepath, "\n".join(markdown_lines))
        logger.debug("Markdown file generated: %s", filepath)
        return filepath
    except Exception as e:
        logger.exception("Error writing markdown file %s: %s", filepath, e)
        return None
