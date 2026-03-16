"""
Celery app for Boost Data Collector.
Beat schedule is in settings.CELERY_BEAT_SCHEDULE (daily 1:00 AM PST).

On Windows the default worker pool (prefork) causes PermissionError [WinError 5].
Use the solo pool on Windows so tasks run in the main process.

Logging: use Django LOGGING so worker/beat log to the same file and handlers as
management commands (console + rotating file, and optional Discord/Slack on ERROR).
"""

import os
import sys

# Logger level follows Django LOG_LEVEL (worker and beat).
from django.conf import settings

from logging.config import dictConfig

from celery import Celery
from celery.signals import setup_logging

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@setup_logging.connect
def on_celery_setup_logging(**kwargs):
    """Apply Django LOGGING so Celery worker/beat use the same log file and handlers."""
    if hasattr(settings, "LOGGING") and settings.LOGGING:
        dictConfig(settings.LOGGING)


# Avoid PermissionError on Windows: prefork pool uses semaphores that fail there.
if sys.platform == "win32":
    app.conf.worker_pool = "solo"
