"""
Test-only Django settings.
Imports base settings, then overrides for fast and isolated tests.
"""
from pathlib import Path

from .settings import *  # noqa: F401, F403

# Use SQLite in-memory for speed when DATABASE_URL not set (e.g. local pytest).
# CI can set DATABASE_URL=sqlite:///test.sqlite3 or leave unset for :memory:
import os
if not os.environ.get("DATABASE_URL", "").strip():
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }

# Faster password hashing in tests
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# No real email in tests
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Avoid writing logs to disk in tests (console only)
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

# Keep workspace and logs under a test subdir so they don't clash
BASE_DIR = Path(__file__).resolve().parent.parent
_test_dir = BASE_DIR / ".test_artifacts"
_test_dir.mkdir(exist_ok=True)
WORKSPACE_DIR = _test_dir / "workspace"
WORKSPACE_DIR.mkdir(exist_ok=True)
for _slug in ("github_activity_tracker", "boost_library_tracker", "shared"):
    (WORKSPACE_DIR / _slug).mkdir(parents=True, exist_ok=True)
LOG_DIR = _test_dir / "logs"
LOG_DIR.mkdir(exist_ok=True)

# No real GitHub tokens in tests
GITHUB_TOKEN = ""
GITHUB_TOKENS_SCRAPING = []
GITHUB_TOKEN_WRITE = ""
