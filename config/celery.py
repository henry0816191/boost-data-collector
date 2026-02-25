"""
Celery app for Boost Data Collector.
Beat schedule is in settings.CELERY_BEAT_SCHEDULE (daily 1:00 AM PST).

On Windows the default worker pool (prefork) causes PermissionError [WinError 5].
Use the solo pool on Windows so tasks run in the main process.
"""

import os
import sys

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Avoid PermissionError on Windows: prefork pool uses semaphores that fail there.
if sys.platform == "win32":
    app.conf.worker_pool = "solo"
