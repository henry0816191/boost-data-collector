"""
Management command: run_scheduled_collectors
Runs collector commands from config/boost_collector_schedule.yaml for a given schedule.
Use --schedule daily | weekly | monthly | on_release | interval; for weekly pass --day-of-week; for monthly --day-of-month; for interval --interval-minutes (1-180).
Exits with 0 only when all succeed; non-zero on any failure.
"""

import logging
import sys
from datetime import date

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from boost_collector_runner.schedule_config import get_tasks_for_schedule

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Run collectors from config/boost_collector_schedule.yaml for a given schedule (daily, weekly, monthly, interval, on_release)."""

    help = (
        "Run collectors from YAML schedule. "
        "Use --schedule daily|weekly|monthly|on_release|interval; weekly needs --day-of-week; monthly needs --day-of-month; interval needs --interval-minutes (1-180)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--schedule",
            choices=("daily", "weekly", "monthly", "on_release", "interval"),
            required=True,
            help="Schedule type to run.",
        )
        parser.add_argument(
            "--day-of-week",
            type=str,
            default=None,
            help="For weekly: weekday name (e.g. monday, tuesday).",
        )
        parser.add_argument(
            "--day-of-month",
            type=int,
            default=None,
            help="For monthly: day of month 1-31.",
        )
        parser.add_argument(
            "--interval-minutes",
            type=int,
            default=None,
            help="For interval: run every N minutes (1-180, at most 3 hours).",
        )
        parser.add_argument(
            "--group",
            type=str,
            default=None,
            help="Run only this group's tasks (for daily/weekly/monthly). Omit for interval or to run all groups.",
        )
        parser.add_argument(
            "--stop-on-failure",
            action="store_true",
            help="Stop running remaining collectors after the first failure.",
        )

    def _get_group_batch_tasks(self, group_id):
        """Return list of (group_id, task_dict) for this group: daily + weekly(today) + monthly(today) + on_release(if new release)."""
        today = date.today()
        today_weekday = today.strftime("%A").lower()
        today_day = today.day
        tasks = []
        tasks.extend(get_tasks_for_schedule("daily", group_id=group_id))
        tasks.extend(
            get_tasks_for_schedule(
                "weekly", day_of_week=today_weekday, group_id=group_id
            )
        )
        tasks.extend(
            get_tasks_for_schedule("monthly", day_of_month=today_day, group_id=group_id)
        )
        try:
            from boost_library_tracker.release_check import has_new_boost_release

            if has_new_boost_release():
                tasks.extend(get_tasks_for_schedule("on_release", group_id=group_id))
        except ImportError:
            pass
        return tasks

    def handle(self, *args, **options):
        """Resolve tasks from YAML (group batch or single schedule), run them sequentially, exit non-zero on failure."""
        schedule_kind = options["schedule"]
        day_of_week = options.get("day_of_week")
        day_of_month = options.get("day_of_month")
        interval_minutes = options.get("interval_minutes")
        stop_on_failure = options["stop_on_failure"]

        if schedule_kind == "weekly" and not day_of_week:
            raise CommandError("--schedule weekly requires --day-of-week")
        if schedule_kind == "monthly" and day_of_month is None:
            raise CommandError("--schedule monthly requires --day-of-month")
        if schedule_kind == "interval" and interval_minutes is None:
            raise CommandError(
                "--schedule interval requires --interval-minutes (1-180)"
            )

        group_id = options.get("group")
        if group_id and schedule_kind == "daily":
            try:
                tasks = self._get_group_batch_tasks(group_id)
            except FileNotFoundError as e:
                raise CommandError(str(e)) from e
            except ValueError as e:
                raise CommandError(str(e)) from e
        else:
            if schedule_kind == "on_release":
                try:
                    from boost_library_tracker.release_check import (
                        has_new_boost_release,
                    )
                except ImportError as e:
                    raise CommandError(
                        "on_release requires boost_library_tracker (install and add to INSTALLED_APPS)."
                    ) from e
                if not has_new_boost_release():
                    logger.info(
                        "run_scheduled_collectors: no new Boost release; skipping on_release tasks."
                    )
                    return
            group_id = (
                group_id if schedule_kind not in ("interval", "on_release") else None
            )
            try:
                tasks = get_tasks_for_schedule(
                    schedule_kind,
                    day_of_week=day_of_week,
                    day_of_month=day_of_month,
                    interval_minutes=interval_minutes,
                    group_id=group_id,
                )
            except FileNotFoundError as e:
                raise CommandError(str(e)) from e
            except ValueError as e:
                raise CommandError(str(e)) from e

        if not tasks:
            logger.info(
                "run_scheduled_collectors: no enabled tasks for schedule=%s",
                schedule_kind,
            )
            self.stdout.write(
                self.style.WARNING(f"No tasks for schedule={schedule_kind}.")
            )
            return

        results = []
        exit_code = 0
        logger.info(
            "run_scheduled_collectors: starting schedule=%s (%d tasks)",
            schedule_kind,
            len(tasks),
        )

        for task_group_id, task in tasks:
            name = task.get("command")
            args = task.get("args") or []
            self.stdout.write(f"Running {name}...")
            try:
                call_command(name, *args)
                results.append((name, 0))
                self.stdout.write(self.style.SUCCESS(f"  {name}: success"))
            except CommandError as e:
                code = getattr(e, "returncode", 1) or 1
                results.append((name, code))
                logger.error("%s failed", name)
                exit_code = code
                if stop_on_failure:
                    break
            except Exception:
                logger.exception("%s failed", name)
                results.append((name, -1))
                exit_code = 1
                if stop_on_failure:
                    break

        succeeded = sum(1 for _, code in results if code == 0)
        failed = len(results) - succeeded
        logger.info(
            "run_scheduled_collectors: finished; succeeded=%d, failed=%d",
            succeeded,
            failed,
        )
        summary = f"Summary: {succeeded} succeeded, {failed} failed."
        if failed == 0:
            self.stdout.write(self.style.SUCCESS(summary))
        else:
            self.stdout.write(self.style.WARNING(summary))

        if exit_code != 0:
            sys.exit(exit_code)
