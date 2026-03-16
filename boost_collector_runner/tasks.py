"""
Celery tasks for boost_collector_runner app.
Runs run_scheduled_collectors (YAML-driven) via management command.
"""

import logging

from celery import shared_task
from django.core.management import call_command

logger = logging.getLogger(__name__)


@shared_task
def run_scheduled_collectors_task(
    schedule_kind,
    day_of_week=None,
    day_of_month=None,
    interval_minutes=None,
    group_id=None,
    stop_on_failure=False,
):
    """
    Run collectors that match the given schedule (from YAML).
    For daily/weekly/monthly: group_id is set so only that group's tasks run (groups run in parallel).
    For interval: group_id is None; all interval tasks with that minutes run in one independent task.
    """
    logger.info(
        "run_scheduled_collectors_task: schedule_kind=%s group_id=%s day_of_week=%s day_of_month=%s interval_minutes=%s",
        schedule_kind,
        group_id,
        day_of_week,
        day_of_month,
        interval_minutes,
    )
    try:
        args = ["--schedule", schedule_kind]
        if group_id is not None:
            args.extend(["--group", group_id])
        if day_of_week is not None:
            args.extend(["--day-of-week", str(day_of_week)])
        if day_of_month is not None:
            args.extend(["--day-of-month", str(day_of_month)])
        if interval_minutes is not None:
            args.extend(["--interval-minutes", str(interval_minutes)])
        if stop_on_failure:
            args.append("--stop-on-failure")
        call_command("run_scheduled_collectors", *args)
        logger.info("run_scheduled_collectors_task: finished successfully")
    except SystemExit as e:
        if e.code is None:
            code = 0
        elif isinstance(e.code, int):
            code = e.code
        else:
            code = 1
        if code != 0:
            logger.error(
                "run_scheduled_collectors_task: command exited with code %s",
                code,
            )
            raise RuntimeError(
                f"run_scheduled_collectors exited with code {code}"
            ) from e
        logger.info("run_scheduled_collectors_task: finished successfully")
    except Exception:
        logger.exception("run_scheduled_collectors_task failed")
        raise
