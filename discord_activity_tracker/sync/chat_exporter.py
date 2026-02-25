"""DiscordChatExporter CLI wrapper for user token-based scraping."""

import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from ..workspace import get_workspace_root

logger = logging.getLogger(__name__)


def _get_cli_path() -> Path:
    """Resolve CLI path at call time (workspace may not exist at import time)."""
    return get_workspace_root() / "tools" / "DiscordChatExporter.Cli.exe"


class DiscordChatExporterError(Exception):
    pass


def export_guild_to_json(
    user_token: str,
    guild_id: int,
    output_dir: Path,
    after_date: Optional[datetime] = None,
    before_date: Optional[datetime] = None,
    include_threads: str = "None",
) -> List[Path]:
    """Export all channels from a guild. Returns list of JSON file paths."""
    cli_path = _get_cli_path()
    if not cli_path.exists():
        raise DiscordChatExporterError(
            f"DiscordChatExporter CLI not found at {cli_path}. "
            "Download it from GitHub and place in workspace/discord_activity_tracker/tools/."
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(cli_path),
        "exportguild",
        "--token",
        user_token,
        "--guild",
        str(guild_id),
        "--output",
        str(output_dir) + "\\",  # trailing slash = directory output
        "--format",
        "Json",
        "--include-threads",
        include_threads,
        "--parallel",
        "3",
        "--respect-rate-limits",
        "True",
        "--markdown",
        "True",
    ]

    if after_date:
        after_str = after_date.strftime("%Y-%m-%d %H:%M:%S")
        cmd.extend(["--after", after_str])
        logger.info(f"Incremental sync: exporting messages after {after_str}")

    if before_date:
        before_str = before_date.strftime("%Y-%m-%d %H:%M:%S")
        cmd.extend(["--before", before_str])
        logger.info(f"Exporting messages before {before_str}")

    logger.info(f"Running DiscordChatExporter for guild {guild_id}")
    logger.debug(f"Command: {' '.join(cmd[:6])}... (token hidden)")

    try:
        # Clear proxy env vars that block DiscordChatExporter
        env = {
            k: v
            for k, v in os.environ.items()
            if k.lower() not in ("http_proxy", "https_proxy")
        }

        # No timeout — full exports can take hours
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        # CLI writes progress to stdout
        stdout_lines = []
        for line in process.stdout:
            line = line.rstrip()
            if line:
                stdout_lines.append(line)
                logger.info(f"[CLI] {line}")

        process.wait()
        stderr = process.stderr.read() if process.stderr else ""

        if process.returncode != 0:
            error_msg = (
                f"DiscordChatExporter failed with exit code {process.returncode}"
            )
            if stderr:
                error_msg += f"\nError: {stderr.strip()}"
            logger.error(error_msg)
            raise DiscordChatExporterError(error_msg)

        logger.info("Export completed successfully")

    except DiscordChatExporterError:
        raise

    except Exception as e:
        logger.exception(f"Unexpected error running DiscordChatExporter: {e}")
        raise DiscordChatExporterError(f"Unexpected error: {e}") from e

    json_files = list(output_dir.glob("*.json"))
    logger.info(f"Found {len(json_files)} exported JSON files")

    return json_files


def parse_exported_json(json_path: Path) -> Dict[str, Any]:
    """Parse a DiscordChatExporter JSON file into a dict with guild, channel, messages."""
    logger.debug(f"Parsing {json_path.name}")

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from {json_path}: {e}")
        raise
    except Exception as e:
        logger.exception(f"Error reading {json_path}: {e}")
        raise


def convert_exporter_message_to_dict(msg_data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert DiscordChatExporter message format to our internal format."""
    author = msg_data.get("author", {})

    converted = {
        "id": msg_data["id"],
        "content": msg_data.get("content", ""),
        "created_at": msg_data["timestamp"],
        "edited_at": msg_data.get("timestampEdited"),
        "author": {
            "id": author.get("id"),
            "username": author.get("name", "unknown"),
            "global_name": author.get("nickname") or author.get("name", "unknown"),
            "avatar": None,
            "bot": author.get("isBot", False),
        },
        "attachments": [
            {"url": att.get("url")} for att in msg_data.get("attachments", [])
        ],
        "reactions": [
            {
                "emoji": {"name": reaction.get("emoji", {}).get("name")},
                "count": reaction.get("count", 0),
            }
            for reaction in msg_data.get("reactions", [])
        ],
        "reference": None,
    }

    if "reference" in msg_data and msg_data["reference"]:
        ref = msg_data["reference"]
        converted["reference"] = {"message_id": ref.get("messageId")}

    return converted


def export_and_parse_guild(
    user_token: str,
    guild_id: int,
    output_dir: Path,
    after_date: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Export guild via CLI and parse all resulting JSON files."""
    json_files = export_guild_to_json(
        user_token=user_token,
        guild_id=guild_id,
        output_dir=output_dir,
        after_date=after_date,
    )

    parsed_channels = []

    for json_path in json_files:
        try:
            data = parse_exported_json(json_path)

            parsed_channels.append(
                {
                    "guild": data.get("guild", {}),
                    "channel": data.get("channel", {}),
                    "messages": data.get("messages", []),
                    "file_path": json_path,
                }
            )

        except Exception as e:
            logger.error(f"Failed to process {json_path.name}: {e}")
            continue

    return parsed_channels
