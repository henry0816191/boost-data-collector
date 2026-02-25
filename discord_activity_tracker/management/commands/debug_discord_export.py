"""Inspect reply data and raw markdown output."""

from django.core.management.base import BaseCommand

from discord_activity_tracker.models import DiscordMessage
from discord_activity_tracker.sync.export import generate_markdown_content


class Command(BaseCommand):
    help = "Inspect reply links and exported markdown"

    def add_arguments(self, parser):
        parser.add_argument(
            "--message-id",
            type=int,
            help="Inspect a specific message by message_id (Discord message ID)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=5,
            help="Number of reply messages to show (default: 5)",
        )

    def handle(self, *args, **options):
        msg_id = options.get("message_id")
        limit = options["limit"]

        if msg_id:
            self._inspect_message(msg_id)
        else:
            self._list_replies(limit)

    def _inspect_message(self, msg_id: int):
        """Show one message, its reply target, and raw markdown."""
        try:
            msg = DiscordMessage.objects.select_related(
                "author", "channel", "channel__server"
            ).get(message_id=msg_id)
        except DiscordMessage.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Message {msg_id} not found in DB"))
            return

        self.stdout.write(f"\n=== Message {msg_id} ===")
        self.stdout.write(f"  Author: @{msg.author.username} (id={msg.author_id})")
        self.stdout.write(f"  Channel: #{msg.channel.channel_name}")
        self.stdout.write(f"  Content length: {len(msg.content or '')} chars")
        self.stdout.write(f"  reply_to_message_id: {msg.reply_to_message_id}")

        if msg.reply_to_message_id:
            try:
                reply_to = DiscordMessage.objects.select_related("author").get(
                    message_id=msg.reply_to_message_id
                )
                self.stdout.write("\n  REPLY TO (found in DB):")
                self.stdout.write(f"    Author: @{reply_to.author.username}")
                self.stdout.write(f"    Content: {(reply_to.content or '')[:100]}...")
            except DiscordMessage.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(
                        f"\n  REPLY TO: message {msg.reply_to_message_id} NOT in DB"
                    )
                )

        self.stdout.write("\n--- Raw markdown ---")
        md = generate_markdown_content(
            msg.channel, "2026-02", [msg], date_str="2026-02-10", split_by_day=True
        )
        lines = md.split("\n")
        in_block = False
        for line in lines:
            if line.startswith("### ") and msg.author.username in line:
                in_block = True
            elif in_block and line.startswith("### "):
                break
            if in_block:
                self.stdout.write(line)
        self.stdout.write("")

    def _list_replies(self, limit: int):
        """List recent reply messages."""
        replies = (
            DiscordMessage.objects.select_related("author", "channel")
            .filter(reply_to_message_id__isnull=False)
            .order_by("-message_created_at")[:limit]
        )

        self.stdout.write(f"\n=== Last {limit} reply messages ===")
        for msg in replies:
            reply_to_exists = DiscordMessage.objects.filter(
                message_id=msg.reply_to_message_id
            ).exists()
            status = "✓" if reply_to_exists else "✗ reply_to NOT in DB"
            self.stdout.write(
                f"  {msg.message_id}: @{msg.author.username} -> reply_to={msg.reply_to_message_id} {status}"
            )

        self.stdout.write("\nUse --message-id <id> to inspect a specific message")
