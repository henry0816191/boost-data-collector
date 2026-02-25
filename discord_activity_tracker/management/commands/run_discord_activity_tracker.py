"""Django management command - sync messages and export to markdown."""

import logging
from pathlib import Path

from django.core.management.base import BaseCommand
from django.conf import settings

from discord_activity_tracker.models import DiscordServer, DiscordChannel
from discord_activity_tracker.sync.messages import sync_all_channels
from discord_activity_tracker.sync.export import export_and_push

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run Discord Activity Tracker: sync messages and export to markdown"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview actions without executing them",
        )
        parser.add_argument(
            "--task",
            type=str,
            default=None,
            help="Task to run: sync, export, or all (default: all)",
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
            help="Number of months to export (default: 12)",
        )
        parser.add_argument(
            "--active-days",
            type=int,
            default=30,
            help="Number of days to consider a channel active (default: 30)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        task_filter = (options["task"] or "").strip().lower()
        full_sync = options["full_sync"]
        months = options["months"]
        active_days = options["active_days"]

        try:
            # Get settings
            token = getattr(settings, "DISCORD_TOKEN", None)
            guild_id = getattr(settings, "DISCORD_SERVER_ID", None)
            context_repo_path = getattr(settings, "DISCORD_CONTEXT_REPO_PATH", None)

            # Validate settings
            if not token:
                self.stdout.write(self.style.ERROR("DISCORD_TOKEN not configured"))
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

            # Task 1: Sync Discord messages
            if not task_filter or task_filter == "sync" or task_filter == "all":
                self._task_sync_messages(
                    dry_run=dry_run,
                    token=token,
                    guild_id=guild_id,
                    full_sync=full_sync,
                    active_days=active_days,
                )

            # Task 2: Export to markdown
            if not task_filter or task_filter == "export" or task_filter == "all":
                self._task_export_markdown(
                    dry_run=dry_run,
                    guild_id=guild_id,
                    context_repo_path=context_repo_path,
                    months=months,
                    active_days=active_days,
                )

            self.stdout.write(
                self.style.SUCCESS("✓ Discord activity tracker completed")
            )

        except Exception as e:
            logger.exception("Discord activity tracker failed: %s", e)
            raise

    def _task_sync_messages(
        self,
        dry_run: bool,
        token: str,
        guild_id: int,
        full_sync: bool,
        active_days: int,
    ):
        """Sync messages from Discord API to database."""
        self.stdout.write("Task 1: Syncing Discord messages...")

        if dry_run:
            # Preview what would be synced
            try:
                server = DiscordServer.objects.get(server_id=guild_id)
                channels = DiscordChannel.objects.filter(server=server)

                if not full_sync:
                    from datetime import timedelta
                    from django.utils import timezone

                    cutoff = timezone.now() - timedelta(days=active_days)
                    channels = channels.filter(last_activity_at__gte=cutoff)

                self.stdout.write(f"  Would sync {channels.count()} channels")
                for channel in channels:
                    last_sync = channel.last_synced_at or "never"
                    self.stdout.write(
                        f"    - #{channel.channel_name} (last sync: {last_sync})"
                    )

            except DiscordServer.DoesNotExist:
                self.stdout.write(f"  Would sync server {guild_id} (first time)")

            return

        # Actual sync
        logger.info(f"Syncing messages from Discord guild {guild_id}")

        sync_all_channels(
            token=token,
            guild_id=guild_id,
            since_date=None,
            full_sync=full_sync,
            active_only=not full_sync,  # If full sync, include all channels
            active_days=active_days,
        )

        # Report results
        server = DiscordServer.objects.get(server_id=guild_id)
        total_channels = DiscordChannel.objects.filter(server=server).count()
        total_messages = sum(
            channel.messages.count()
            for channel in DiscordChannel.objects.filter(server=server)
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"  ✓ Synced {total_channels} channels, {total_messages} total messages"
            )
        )

    def _task_export_markdown(
        self,
        dry_run: bool,
        guild_id: int,
        context_repo_path: Path,
        months: int,
        active_days: int,
    ):
        """Export to markdown files and push to context repo."""
        self.stdout.write("Task 2: Exporting to markdown...")

        try:
            server = DiscordServer.objects.get(server_id=guild_id)
        except DiscordServer.DoesNotExist:
            self.stdout.write(
                self.style.WARNING(
                    "  Server not found in database. Run sync task first."
                )
            )
            return

        if dry_run:
            from datetime import timedelta
            from django.utils import timezone

            cutoff = timezone.now() - timedelta(days=active_days)
            channels = DiscordChannel.objects.filter(
                server=server, last_activity_at__gte=cutoff
            )

            self.stdout.write(
                f"  Would export {channels.count()} active channels to {context_repo_path}"
            )
            self.stdout.write(f"  Months back: {months}")
            self.stdout.write(f"  Active days threshold: {active_days}")

            for channel in channels:
                self.stdout.write(f"    - #{channel.channel_name}")

            return

        logger.info(f"Exporting to markdown: {context_repo_path}")

        success = export_and_push(
            context_repo_path=context_repo_path,
            server=server,
            months_back=months,
            active_days=active_days,
            auto_commit=False,
        )

        if success:
            self.stdout.write(
                self.style.SUCCESS(f"  ✓ Exported to {context_repo_path}")
            )
        else:
            self.stdout.write(self.style.WARNING("  ⚠ Export failed"))
