"""
Celery tasks for workflow app.
Runs run_all_collectors management command (e.g. from Celery Beat at 1 AM PST).
"""

import logging

from celery import shared_task
from django.core.management import call_command

logger = logging.getLogger(__name__)


@shared_task
def run_all_collectors_task(stop_on_failure=False):
    """Run the run_all_collectors management command. Used by Celery Beat for daily schedule."""
    logger.info(
        "run_all_collectors_task: starting (stop_on_failure=%s)",
        stop_on_failure,
    )
    try:
        args = ["--stop-on-failure"] if stop_on_failure else []
        call_command("run_all_collectors", *args)
        logger.info("run_all_collectors_task: finished successfully")
    except SystemExit as e:
        if e.code != 0:
            logger.error("run_all_collectors_task: command exited with code %s", e.code)
            raise
    except Exception as e:
        logger.exception("run_all_collectors_task failed: %s", e)
        raise
