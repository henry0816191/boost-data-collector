"""Test settings - SQLite in-memory, fast hashing, isolated workspace."""
import os
from pathlib import Path

from .settings import *  # noqa: F401, F403

if not os.environ.get("DATABASE_URL", "").strip():
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{levelname} {message}", "style": "{"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
}

BASE_DIR = Path(__file__).resolve().parent.parent
_test_dir = BASE_DIR / ".test_artifacts"
_test_dir.mkdir(exist_ok=True)
WORKSPACE_DIR = _test_dir / "workspace"
WORKSPACE_DIR.mkdir(exist_ok=True)
for _slug in ("github_activity_tracker", "boost_library_tracker", "shared"):
    (WORKSPACE_DIR / _slug).mkdir(parents=True, exist_ok=True)
LOG_DIR = _test_dir / "logs"
LOG_DIR.mkdir(exist_ok=True)

GITHUB_TOKEN = ""
GITHUB_TOKENS_SCRAPING = []
GITHUB_TOKEN_WRITE = ""
