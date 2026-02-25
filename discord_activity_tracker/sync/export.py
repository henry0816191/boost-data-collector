"""Export Discord messages to markdown files."""

import logging
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List
from collections import defaultdict

from dateutil.relativedelta import relativedelta
from django.utils import timezone as django_timezone

from ..models import DiscordServer, DiscordChannel, DiscordMessage
from .utils import sanitize_channel_name, format_discord_url

logger = logging.getLogger(__name__)

DAY_SPLIT_THRESHOLD = 200


def _make_github_anchor(timestamp: str, username: str) -> str:
    """Build anchor that matches GitHub's auto-generated one for a heading."""
    safe_ts = timestamp.replace(":", "").replace(".", "")
    safe_user = re.sub(r"[^a-z0-9]", "", username.lower())
    return f"{safe_ts}-utc--{safe_user}"


_INVISIBLE_UNICODE = re.compile("[\u200b-\u200d\u2060-\u2064\u2066-\u2069\ufeff]+")


def _strip_invisible_unicode(text: str) -> str:
    """Strip invisible chars (zero-width, isolates, BOM) that mess up markdown."""
    if not text:
        return text
    return _INVISIBLE_UNICODE.sub("", text)


def _sanitize_discord_content(content: str) -> str:
    """Convert Discord mentions to plain text, keep code blocks intact."""
    if not content:
        return ""
    content = _strip_invisible_unicode(content)

    def replace_mentions(text: str) -> str:
        text = re.sub(r"<@!?(\d+)>", r"@user-\1", text)
        text = re.sub(r"<@&(\d+)>", r"@role-\1", text)
        text = re.sub(r"<#(\d+)>", r"#channel-\1", text)
        text = re.sub(r"<a?:(\w+):\d+>", r":\1:", text)
        return text

    parts = re.split(r"(```[\s\S]*?```|`[^`]*`)", content)
    result = []
    for part in parts:
        if part.startswith("`") and part.endswith("`"):
            result.append(part)
        else:
            result.append(replace_mentions(part))
    return "".join(result)


def generate_markdown_content(
    channel: DiscordChannel,
    year_month: str,
    messages: List[DiscordMessage],
    date_str: Optional[str] = None,
    split_by_day: bool = False,
) -> str:
    """Build markdown for a channel-month or channel-day."""
    lines = []

    if messages:
        first_msg = messages[0]
        last_msg = messages[-1]
        message_count = len(messages)
        unique_authors = set(msg.author_id for msg in messages)
        active_users = len(unique_authors)
    else:
        first_msg = last_msg = None
        message_count = active_users = 0

    # YAML frontmatter
    lines.append("---")
    lines.append(f"channel: {channel.channel_name}")
    if date_str:
        lines.append(f"date: {date_str}")
    else:
        lines.append(f"month: {year_month}")
    lines.append(f"server: {channel.server.server_name}")
    lines.append(f"message_count: {message_count}")
    lines.append(f"active_users: {active_users}")

    if first_msg:
        first_utc = first_msg.message_created_at.astimezone(django_timezone.utc)
        lines.append(f"first_message: {first_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    if last_msg:
        last_utc = last_msg.message_created_at.astimezone(django_timezone.utc)
        lines.append(f"last_message: {last_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}")

    discord_url = format_discord_url(
        channel.server.server_id, channel.channel_id, 0
    ).rsplit("/", 1)[0]
    lines.append(f"discord_channel_url: {discord_url}")
    lines.append("---")
    lines.append("")

    # Title
    if date_str:
        lines.append(f"# #{channel.channel_name} - {date_str}")
    else:
        month_name = datetime.strptime(year_month, "%Y-%m").strftime("%B %Y")
        lines.append(f"# #{channel.channel_name} - {month_name}")
    lines.append("")

    # Group by date (UTC)
    messages_by_date = defaultdict(list)
    for msg in messages:
        utc_time = msg.message_created_at.astimezone(django_timezone.utc)
        d = utc_time.strftime("%Y-%m-%d")
        messages_by_date[d].append(msg)

    safe_channel_name = sanitize_channel_name(channel.channel_name)

    for d in sorted(messages_by_date.keys()):
        lines.append(f"## {d}")
        lines.append("")

        for msg in messages_by_date[d]:
            # UTC timestamp (with ms)
            utc_time = msg.message_created_at.astimezone(django_timezone.utc)
            timestamp = utc_time.strftime("%H:%M:%S")
            if utc_time.microsecond:
                timestamp += f".{utc_time.microsecond // 1000:03d}"

            author_label = f"@{msg.author.username}"
            if getattr(msg.author, "is_bot", False):
                author_label += " (bot)"
            lines.append(f"### {timestamp} UTC — {author_label}")
            lines.append("")

            msg_url = format_discord_url(
                channel.server.server_id, channel.channel_id, msg.message_id
            )

            # Reply, Url (blockquoted)
            metadata_lines = []
            if msg.reply_to_message_id:
                try:
                    reply_to = DiscordMessage.objects.get(
                        message_id=msg.reply_to_message_id
                    )
                    reply_utc = reply_to.message_created_at.astimezone(
                        django_timezone.utc
                    )
                    reply_time = reply_utc.strftime("%H:%M:%S")
                    if reply_utc.microsecond:
                        reply_time += f".{reply_utc.microsecond // 1000:03d}"
                    reply_date = reply_utc.strftime("%Y-%m-%d")
                    reply_anchor = _make_github_anchor(
                        reply_time, reply_to.author.username
                    )

                    if reply_date == d:
                        link_target = f"#{reply_anchor}"
                    elif split_by_day:
                        link_target = (
                            f"../{reply_date}/{safe_channel_name}.md#{reply_anchor}"
                        )
                    elif reply_date.startswith(year_month):
                        link_target = f"#{reply_anchor}"
                    else:
                        reply_ym = reply_date[:7]
                        link_target = f"../{reply_ym}/{reply_ym}-{safe_channel_name}.md#{reply_anchor}"

                    metadata_lines.append(
                        f"> Reply to: [@{reply_to.author.username} ({reply_time} UTC)]({link_target})  "
                    )
                    if reply_to.content:
                        preview = _sanitize_discord_content(
                            reply_to.content.replace("\n", " ").strip()[:80]
                        )
                        if len(reply_to.content.strip()) > 80:
                            preview += "..."
                        metadata_lines.append(f"> Original: {preview}  ")
                except DiscordMessage.DoesNotExist:
                    pass
            metadata_lines.append(f"> Url: {msg_url}  ")
            for m in metadata_lines:
                lines.append(m)
            lines.append("")
            lines.append("")

            if msg.content:
                sanitized = _sanitize_discord_content(msg.content)
                if sanitized.strip().startswith("```"):
                    lines.append("<!-- -->")
                    lines.append("")
                in_code_fence = False
                for content_line in sanitized.splitlines():
                    if content_line.startswith("```"):
                        in_code_fence = not in_code_fence
                        lines.append(content_line)
                    elif in_code_fence:
                        lines.append(content_line)
                    else:
                        lines.append(content_line + "  ")
                if in_code_fence:
                    lines.append("```")  # close unclosed block
            lines.append("")

            if msg.attachment_urls:
                lines.append("> Attachments:  ")
                for url in msg.attachment_urls:
                    filename = url.split("/")[-1].split("?")[0]
                    lines.append(f"> - [{filename}]({url})  ")
                lines.append("")

            lines.append("")

    return "\n".join(lines)


def export_channel_to_markdown(
    channel: DiscordChannel, year_month: str, output_dir: Path
) -> Optional[List[Path]]:
    """Export a channel-month to markdown. Splits into per-day files."""
    logger.info(f"Exporting #{channel.channel_name} for {year_month}")

    start_date = datetime.strptime(f"{year_month}-01", "%Y-%m-%d")
    start_date = django_timezone.make_aware(start_date)
    end_date = start_date + relativedelta(months=1)

    messages = (
        DiscordMessage.objects.filter(
            channel=channel,
            message_created_at__gte=start_date,
            message_created_at__lt=end_date,
            is_deleted=False,
        )
        .select_related("author")
        .order_by("message_created_at")
    )

    message_list = list(messages)

    if not message_list:
        logger.debug(
            f"No messages for #{channel.channel_name} in {year_month}, skipping"
        )
        return None

    year = year_month.split("-")[0]
    month_dir = output_dir / year / year_month
    month_dir.mkdir(parents=True, exist_ok=True)
    safe_channel_name = sanitize_channel_name(channel.channel_name)

    # Per-day: yyyy/yyyy-MM/yyyy-MM-DD/channel.md
    messages_by_date = defaultdict(list)
    for msg in message_list:
        utc_time = msg.message_created_at.astimezone(django_timezone.utc)
        d = utc_time.strftime("%Y-%m-%d")
        messages_by_date[d].append(msg)

    exported_paths = []

    for date_str in sorted(messages_by_date.keys()):
        day_messages = messages_by_date[date_str]
        md_content = generate_markdown_content(
            channel, year_month, day_messages, date_str=date_str, split_by_day=True
        )
        day_dir = month_dir / date_str
        day_dir.mkdir(parents=True, exist_ok=True)
        file_path = day_dir / f"{safe_channel_name}.md"
        file_path.write_text(md_content, encoding="utf-8")
        exported_paths.append(file_path)
        logger.info(f"Exported {len(day_messages)} messages to {file_path}")

    return exported_paths


def export_all_active_channels(
    context_repo_path: Path,
    server: DiscordServer,
    months_back: int = 12,
    active_days: int = 30,
) -> List[Path]:
    """Export active channels for the last N months."""
    logger.info(f"Exporting all active channels for last {months_back} months")

    cutoff = django_timezone.now() - timedelta(days=active_days)
    channels = (
        DiscordChannel.objects.filter(server=server, last_activity_at__gte=cutoff)
        .select_related("server")
        .order_by("position", "channel_name")
    )

    logger.info(f"Found {channels.count()} active channels")

    exported_files = []

    today = django_timezone.now()
    for i in range(months_back):
        month_date = today - relativedelta(months=i)
        year_month = month_date.strftime("%Y-%m")

        for channel in channels:
            try:
                result = export_channel_to_markdown(
                    channel, year_month, context_repo_path
                )
                if result:
                    exported_files.extend(result)
            except Exception as e:
                logger.error(
                    f"Failed to export #{channel.channel_name} for {year_month}: {e}"
                )
                continue

    logger.info(f"Exported {len(exported_files)} files")
    return exported_files


def commit_and_push_context_repo(
    repo_path: Path, commit_message: Optional[str] = None
) -> bool:
    """Commit and push to the context repo."""
    if commit_message is None:
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        commit_message = f"Update Discord archive - {timestamp}"

    logger.info(f"Committing and pushing to {repo_path}")

    try:
        result = subprocess.run(
            ["git", "add", "."],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
        )
        logger.debug(f"git add: {result.stdout}")

        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
        )

        if not result.stdout.strip():
            logger.info("No changes to commit")
            return True

        result = subprocess.run(
            ["git", "commit", "-m", commit_message],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
        )
        logger.info(f"git commit: {result.stdout}")

        result = subprocess.run(
            ["git", "push"], cwd=repo_path, check=True, capture_output=True, text=True
        )
        logger.info(f"git push: {result.stdout}")

        logger.info("Successfully committed and pushed changes")
        return True

    except subprocess.CalledProcessError as e:
        logger.error(f"Git operation failed: {e.stderr}")
        return False
    except Exception as e:
        logger.exception(f"Error committing and pushing: {e}")
        return False


def export_and_push(
    context_repo_path: Path,
    server: DiscordServer,
    months_back: int = 12,
    active_days: int = 30,
    commit_message: Optional[str] = None,
    auto_commit: bool = False,
) -> bool:
    """Export channels, optionally commit and push."""
    exported_files = export_all_active_channels(
        context_repo_path=context_repo_path,
        server=server,
        months_back=months_back,
        active_days=active_days,
    )

    if not exported_files:
        logger.warning("No files exported, skipping git operations")
        return False

    if auto_commit:
        success = commit_and_push_context_repo(context_repo_path, commit_message)
        return success
    else:
        logger.info(f"Exported {len(exported_files)} files (auto-commit disabled)")
        return True
