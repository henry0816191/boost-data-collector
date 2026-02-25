# Load Celery app when Django starts so that @shared_task and autodiscover use it.
from .celery import app as celery_app

__all__ = ("celery_app",)
