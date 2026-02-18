"""Django management command - sync using DiscordChatExporter CLI with user token."""

import logging
from pathlib import Path
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone as django_timezone
from asgiref.sync import sync_to_async

from discord_activity_tracker.models import DiscordServer, DiscordChannel
from discord_activity_tracker.sync.chat_exporter import (
    export_guild_to_json,
    parse_exported_json,
    convert_exporter_message_to_dict,
)
from discord_activity_tracker.sync.messages import (
    _process_messages_in_batches,
)
from discord_activity_tracker.sync.utils import parse_datetime
from discord_activity_tracker.sync.export import export_and_push
from discord_activity_tracker.services import (
    get_or_create_discord_server,
    get_or_create_discord_channel,
    update_channel_last_synced,
    update_channel_last_activity,
)
from discord_activity_tracker.workspace import get_raw_dir

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Run Discord Activity Tracker using DiscordChatExporter CLI (user token method)"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview actions without writing to database",
        )
        parser.add_argument(
            "--task",
            type=str,
            default="all",
            choices=["sync", "export", "all", "import-only"],
            help="Task to run: sync, export, all, or import-only (default: all)",
        )
        parser.add_argument(
            "--full-sync",
            action="store_true",
            help="Sync all messages (ignore last_synced_at)",
        )
        parser.add_argument(
            "--months",
            type=int,
            default=12,
            help="Number of months to export to markdown (default: 12)",
        )
        parser.add_argument(
            "--active-days",
            type=int,
            default=30,
            help="Number of days to consider a channel active (default: 30)",
        )
        parser.add_argument(
            "--days-back",
            type=int,
            default=30,
            help="Number of days back to sync messages (default: 30, 0 for all history)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        task = options["task"]
        full_sync = options["full_sync"]
        months = options["months"]
        active_days = options["active_days"]
        days_back = options["days_back"]

        try:
            user_token = getattr(settings, "DISCORD_USER_TOKEN", None)
            guild_id = getattr(settings, "DISCORD_SERVER_ID", None)
            context_repo_path = getattr(settings, "DISCORD_CONTEXT_REPO_PATH", None)

            if not user_token:
                self.stdout.write(self.style.ERROR("DISCORD_USER_TOKEN not configured"))
                self.stdout.write(
                    "Set it in .env file. See DiscordChatExporter docs for token extraction."
                )
                return

            if not guild_id:
                self.stdout.write(self.style.ERROR("DISCORD_SERVER_ID not configured"))
                return

            if not context_repo_path:
                self.stdout.write(
                    self.style.ERROR("DISCORD_CONTEXT_REPO_PATH not configured")
                )
                return

            context_repo_path = Path(context_repo_path)
            guild_id = int(guild_id)

            if task in ["sync", "all"]:
                self._sync_messages(
                    dry_run=dry_run,
                    user_token=user_token,
                    guild_id=guild_id,
                    full_sync=full_sync,
                    days_back=days_back,
                )

            if task == "import-only":
                self._import_json_files(dry_run=dry_run, guild_id=guild_id)

            if task in ["export", "all", "import-only"]:
                self._export_markdown(
                    dry_run=dry_run,
                    guild_id=guild_id,
                    context_repo_path=context_repo_path,
                    months=months,
                    active_days=active_days,
                )

            self.stdout.write(self.style.SUCCESS("✓ Discord exporter completed"))

        except Exception as e:
            logger.exception("Discord exporter failed: %s", e)
            self.stdout.write(self.style.ERROR(f"Error: {e}"))
            raise

    def _sync_messages(
        self,
        dry_run: bool,
        user_token: str,
        guild_id: int,
        full_sync: bool,
        days_back: int,
    ):
        """Export messages via CLI and persist to database."""
        self.stdout.write("\n=== Syncing Messages using DiscordChatExporter ===")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no database writes"))

        temp_dir = get_raw_dir()

        try:
            server = DiscordServer.objects.filter(server_id=guild_id).first()

            after_date = None
            days_back_date = (
                (django_timezone.now() - timedelta(days=days_back))
                if days_back > 0
                else None
            )

            if full_sync:
                after_date = days_back_date
                if after_date:
                    self.stdout.write(
                        f"Full sync - last {days_back} days from: {after_date}"
                    )
                else:
                    self.stdout.write("Full sync - fetching all messages")
            elif server:
                earliest_sync = (
                    DiscordChannel.objects.filter(server=server)
                    .exclude(last_synced_at__isnull=True)
                    .order_by("last_synced_at")
                    .first()
                )

                sync_date = earliest_sync.last_synced_at if earliest_sync else None

                if sync_date and days_back_date:
                    after_date = min(sync_date, days_back_date)
                    self.stdout.write(f"Syncing from: {after_date}")
                elif sync_date:
                    after_date = sync_date
                    self.stdout.write(f"Incremental sync from: {after_date}")
                elif days_back_date:
                    after_date = days_back_date
                    self.stdout.write(
                        f"First sync - last {days_back} days from: {after_date}"
                    )
                else:
                    self.stdout.write("First sync - fetching all messages")
            else:
                after_date = days_back_date
                if after_date:
                    self.stdout.write(
                        f"First sync - last {days_back} days from: {after_date}"
                    )
                else:
                    self.stdout.write("First sync - fetching all messages")

            json_files = export_guild_to_json(
                user_token=user_token,
                guild_id=guild_id,
                output_dir=temp_dir,
                after_date=after_date,
            )

            self.stdout.write(f"Exported {len(json_files)} channel files")

            if dry_run:
                for json_path in json_files:
                    data = parse_exported_json(json_path)
                    ch = data.get("channel", {})
                    msg_count = len(data.get("messages", []))
                    self.stdout.write(f"  #{ch.get('name', '?')}: {msg_count} messages")
                return

            import asyncio

            # Process one file at a time to avoid loading 900MB+ into memory
            for i, json_path in enumerate(json_files, 1):
                try:
                    data = parse_exported_json(json_path)
                    channel_data = {
                        "guild": data.get("guild", {}),
                        "channel": data.get("channel", {}),
                        "messages": data.get("messages", []),
                    }
                    ch_name = channel_data["channel"].get("name", "?")
                    msg_count = len(channel_data["messages"])
                    self.stdout.write(
                        f"  [{i}/{len(json_files)}] #{ch_name}: {msg_count} messages"
                    )
                    asyncio.run(self._persist_exported_data(guild_id, [channel_data]))
                    json_path.unlink()
                except Exception as e:
                    logger.error(f"Failed to process {json_path.name}: {e}")
                    continue

            self.stdout.write("Done persisting all channels")

        except Exception as e:
            logger.exception(f"Sync failed: {e}")
            raise

    async def _persist_exported_data(self, guild_id: int, parsed_data: list):
        """Write parsed channel data to the database using bulk operations."""
        for channel_data in parsed_data:
            try:
                guild_info = channel_data["guild"]
                channel_info = channel_data["channel"]
                messages = channel_data["messages"]

                server, _ = await sync_to_async(get_or_create_discord_server)(
                    server_id=guild_info["id"],
                    server_name=guild_info["name"],
                    icon_url="",
                )

                channel, _ = await sync_to_async(get_or_create_discord_channel)(
                    server=server,
                    channel_id=channel_info["id"],
                    channel_name=channel_info["name"],
                    channel_type=channel_info.get("type", "text"),
                    topic=channel_info.get("topic") or "",
                    position=0,
                )

                # Convert exporter format to internal format for bulk processing
                converted = [convert_exporter_message_to_dict(msg) for msg in messages]

                processed = await _process_messages_in_batches(channel, converted)

                if messages:
                    last_msg = convert_exporter_message_to_dict(messages[-1])
                    last_time = parse_datetime(last_msg.get("created_at"))
                    if last_time:
                        await sync_to_async(update_channel_last_activity)(
                            channel, last_time
                        )

                await sync_to_async(update_channel_last_synced)(channel)

                logger.info(
                    f"Synced #{channel.channel_name}: "
                    f"{processed}/{len(messages)} messages"
                )

            except Exception as e:
                logger.error(
                    f"Failed to persist channel {channel_info.get('name')}: {e}"
                )
                continue

    def _import_json_files(self, dry_run: bool, guild_id: int):
        """Import pre-exported JSON files from workspace/discord_activity_tracker/raw/ into the database."""
        self.stdout.write("\n=== Importing JSON Files ===")

        temp_dir = get_raw_dir()

        json_files = sorted(temp_dir.glob("*.json"))
        if not json_files:
            self.stdout.write(self.style.ERROR(f"No JSON files found in {temp_dir}"))
            return

        self.stdout.write(f"Found {len(json_files)} JSON files")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no database writes"))
            for f in json_files:
                self.stdout.write(f"  {f.name}")
            return

        parsed_data = []
        for json_path in json_files:
            try:
                data = parse_exported_json(json_path)
                parsed_data.append(
                    {
                        "guild": data.get("guild", {}),
                        "channel": data.get("channel", {}),
                        "messages": data.get("messages", []),
                        "file_path": json_path,
                    }
                )
                self.stdout.write(
                    f"  Parsed {json_path.name}: {len(data.get('messages', []))} messages"
                )
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f"  Skipping {json_path.name}: {e}")
                )
                continue

        self.stdout.write(f"Importing {len(parsed_data)} channels...")

        import asyncio

        asyncio.run(self._persist_exported_data(guild_id, parsed_data))

        self.stdout.write(self.style.SUCCESS(f"✓ Imported {len(parsed_data)} channels"))

    def _export_markdown(
        self,
        dry_run: bool,
        guild_id: int,
        context_repo_path: Path,
        months: int,
        active_days: int,
    ):
        """Export to markdown files."""
        self.stdout.write("\n=== Exporting to Markdown ===")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no file writes"))
            return

        try:
            server = DiscordServer.objects.get(server_id=guild_id)
        except DiscordServer.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(
                    f"Server {guild_id} not found in database. Run sync first."
                )
            )
            return

        success = export_and_push(
            context_repo_path=context_repo_path,
            server=server,
            months_back=months,
            active_days=active_days,
            auto_commit=False,
        )

        if success:
            self.stdout.write(self.style.SUCCESS(f"✓ Exported to {context_repo_path}"))
        else:
            self.stdout.write(self.style.WARNING("No files exported"))
