"""Markdown export - generate LLM-friendly files from messages."""
import logging
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


def generate_markdown_content(
    channel: DiscordChannel,
    year_month: str,
    messages: List[DiscordMessage]
) -> str:
    """Generate markdown for one channel-month."""
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

    lines.append("---")
    lines.append(f"channel: {channel.channel_name}")
    lines.append(f"month: {year_month}")
    lines.append(f"server: {channel.server.server_name}")
    lines.append(f"message_count: {message_count}")
    lines.append(f"active_users: {active_users}")

    if first_msg:
        lines.append(f"first_message: {first_msg.message_created_at.isoformat()}")
    if last_msg:
        lines.append(f"last_message: {last_msg.message_created_at.isoformat()}")

    discord_url = format_discord_url(
        channel.server.server_id,
        channel.channel_id,
        0  # Channel URL (no specific message)
    ).rsplit('/', 1)[0]  # Remove the /0 at the end
    lines.append(f"discord_channel_url: {discord_url}")
    lines.append("---")
    lines.append("")

    month_name = datetime.strptime(year_month, "%Y-%m").strftime("%B %Y")
    lines.append(f"# #{channel.channel_name} - {month_name}")
    lines.append("")

    messages_by_date = defaultdict(list)
    for msg in messages:
        date_str = msg.message_created_at.strftime("%Y-%m-%d")
        messages_by_date[date_str].append(msg)

    for date_str in sorted(messages_by_date.keys()):
        lines.append(f"## {date_str}")
        lines.append("")

        for msg in messages_by_date[date_str]:
            timestamp = msg.message_created_at.strftime("%H:%M")
            lines.append(f"### {timestamp} - @{msg.author.username}")
            lines.append("")

            if msg.content:
                lines.append(msg.content)
                lines.append("")

            msg_url = format_discord_url(
                channel.server.server_id,
                channel.channel_id,
                msg.message_id
            )
            lines.append(f"[🔗]({msg_url})")
            lines.append("")

            if msg.reply_to_message_id:
                try:
                    reply_to = DiscordMessage.objects.get(message_id=msg.reply_to_message_id)
                    reply_time = reply_to.message_created_at.strftime("%H:%M")
                    lines.append(f"Reply to: @{reply_to.author.username} ({reply_time})")
                    lines.append("")
                except DiscordMessage.DoesNotExist:
                    pass

            reactions = msg.reactions.all()
            if reactions:
                reaction_strs = [f"{r.emoji} ({r.count})" for r in reactions]
                lines.append(f"Reactions: {', '.join(reaction_strs)}")
                lines.append("")

            if msg.attachment_urls:
                lines.append("Attachments:")
                for url in msg.attachment_urls:
                    filename = url.split("/")[-1].split("?")[0]  # Remove query params
                    lines.append(f"- {filename} ({url})")
                lines.append("")

            lines.append("---")
            lines.append("")

    return "\n".join(lines)


def export_channel_to_markdown(
    channel: DiscordChannel,
    year_month: str,
    output_dir: Path
) -> Optional[Path]:
    """Export one channel-month to a markdown file. Returns path or None."""
    logger.info(f"Exporting #{channel.channel_name} for {year_month}")

    start_date = datetime.strptime(f"{year_month}-01", "%Y-%m-%d")
    start_date = django_timezone.make_aware(start_date)
    end_date = start_date + relativedelta(months=1)

    messages = DiscordMessage.objects.filter(
        channel=channel,
        message_created_at__gte=start_date,
        message_created_at__lt=end_date,
        is_deleted=False
    ).select_related("author").prefetch_related("reactions").order_by("message_created_at")

    message_list = list(messages)

    if not message_list:
        logger.debug(f"No messages for #{channel.channel_name} in {year_month}, skipping")
        return None

    md_content = generate_markdown_content(channel, year_month, message_list)

    # yyyy/yyyy-MM/yyyy-MM-channel-name.md
    year = year_month.split("-")[0]
    month_dir = output_dir / year / year_month
    month_dir.mkdir(parents=True, exist_ok=True)

    safe_channel_name = sanitize_channel_name(channel.channel_name)
    file_path = month_dir / f"{year_month}-{safe_channel_name}.md"

    file_path.write_text(md_content, encoding="utf-8")
    logger.info(f"Exported {len(message_list)} messages to {file_path}")

    return file_path


def export_all_active_channels(
    context_repo_path: Path,
    server: DiscordServer,
    months_back: int = 12,
    active_days: int = 30
) -> List[Path]:
    """Export all active channels for the last N months."""
    logger.info(f"Exporting all active channels for last {months_back} months")

    cutoff = django_timezone.now() - timedelta(days=active_days)
    channels = DiscordChannel.objects.filter(
        server=server,
        last_activity_at__gte=cutoff
    ).select_related("server").order_by("position", "channel_name")

    logger.info(f"Found {channels.count()} active channels")

    exported_files = []

    today = django_timezone.now()
    for i in range(months_back):
        month_date = today - relativedelta(months=i)
        year_month = month_date.strftime("%Y-%m")

        for channel in channels:
            try:
                file_path = export_channel_to_markdown(channel, year_month, context_repo_path)
                if file_path:
                    exported_files.append(file_path)
            except Exception as e:
                logger.error(f"Failed to export #{channel.channel_name} for {year_month}: {e}")
                continue

    logger.info(f"Exported {len(exported_files)} files")
    return exported_files


def commit_and_push_context_repo(
    repo_path: Path,
    commit_message: Optional[str] = None
) -> bool:
    """Git commit and push to context repository."""
    if commit_message is None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        commit_message = f"Update Discord archive - {timestamp}"

    logger.info(f"Committing and pushing to {repo_path}")

    try:
        result = subprocess.run(
            ["git", "add", "."],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True
        )
        logger.debug(f"git add: {result.stdout}")

        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True
        )

        if not result.stdout.strip():
            logger.info("No changes to commit")
            return True

        result = subprocess.run(
            ["git", "commit", "-m", commit_message],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True
        )
        logger.info(f"git commit: {result.stdout}")

        result = subprocess.run(
            ["git", "push"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True
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
    auto_commit: bool = False
) -> bool:
    """Export all active channels and optionally commit+push."""
    exported_files = export_all_active_channels(
        context_repo_path=context_repo_path,
        server=server,
        months_back=months_back,
        active_days=active_days
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
