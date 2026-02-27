"""
Django settings for Boost Data Collector project.
Uses django-environ for environment variables.
"""

from pathlib import Path

import environ

from celery.schedules import crontab

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment
env = environ.Env(
    DEBUG=(bool, False),
    SECRET_KEY=(str, ""),
)
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(str(env_file))

# Security
SECRET_KEY = env("SECRET_KEY") or "django-insecure-dev-only-change-in-production"
DEBUG = env("DEBUG")

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    # Project apps (github_ops before github_activity_tracker - tracker depends on ops)
    "workflow",
    "cppa_user_tracker",
    "github_ops",
    "operations",
    "github_activity_tracker",
    "boost_library_tracker",
    "boost_mailing_list_tracker",
    "cppa_slack_transcript_tracker",
    "discord_activity_tracker",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# Database - PostgreSQL (local or Google Cloud SQL)
# Use DATABASE_URL, or set DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT (and optionally DB_OPTIONS_SSLMODE).
_db_url = (env("DATABASE_URL", default=None) or "").strip()
if _db_url:
    DATABASES = {"default": env.db("DATABASE_URL")}
else:
    _db_options = {}
    if env("DB_OPTIONS_SSLMODE", default=None):
        _db_options["sslmode"] = env("DB_OPTIONS_SSLMODE")
    _default_db = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", default="boost_dashboard"),
        "USER": env("DB_USER", default=""),
        "PASSWORD": env("DB_PASSWORD", default=""),
        "HOST": env("DB_HOST", default="localhost"),
        "PORT": env("DB_PORT", default="5432"),
        **({"OPTIONS": _db_options} if _db_options else {}),
    }
    DATABASES = {"default": _default_db}

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Templates
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
            ],
        },
    },
]

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Workspace: one folder for raw/processed files, subfolders per app (see docs/Workspace.md)
WORKSPACE_DIR = Path(
    env("WORKSPACE_DIR", default=str(BASE_DIR / "workspace"))
).resolve()
_WORKSPACE_APP_SLUGS = (
    "github_activity_tracker",
    "boost_library_tracker",
    "cppa_slack_transcript_tracker",
    "discord_activity_tracker",
    "boost_mailing_list_tracker",
    "shared",
)
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
for _slug in _WORKSPACE_APP_SLUGS:
    (WORKSPACE_DIR / _slug).mkdir(parents=True, exist_ok=True)

# GitHub tokens (multiple use cases: scraping, write)
# - GITHUB_TOKEN: fallback when a specific token is not set
# - GITHUB_TOKENS_SCRAPING: comma-separated list for API read/scraping (round-robin for rate limits)
# - GITHUB_TOKEN_WRITE: for create PR, issue, comment, and git push
GITHUB_TOKEN = (env("GITHUB_TOKEN", default="") or "").strip()
_github_tokens_scraping_str = (env("GITHUB_TOKENS_SCRAPING", default="") or "").strip()
GITHUB_TOKENS_SCRAPING = [
    t.strip() for t in _github_tokens_scraping_str.split(",") if t.strip()
]
if not GITHUB_TOKENS_SCRAPING and GITHUB_TOKEN:
    GITHUB_TOKENS_SCRAPING = [GITHUB_TOKEN]
GITHUB_TOKEN_WRITE = (
    env("GITHUB_TOKEN_WRITE", default="") or ""
).strip() or GITHUB_TOKEN
# Optional: GitHub repo for Slack huddle transcript uploads
GITHUB_SLACK_HUDDLE_REPO_OWNER = (
    env("GITHUB_SLACK_HUDDLE_REPO_OWNER", default="") or ""
).strip()
GITHUB_SLACK_HUDDLE_REPO_NAME = (
    env("GITHUB_SLACK_HUDDLE_REPO_NAME", default="") or ""
).strip()

# Slack (bot + app token for operations.slack_ops and cppa_slack_transcript_tracker)
SLACK_BOT_TOKEN = (env("SLACK_BOT_TOKEN", default="") or "").strip()
SLACK_APP_TOKEN = (env("SLACK_APP_TOKEN", default="") or "").strip()
# Optional: for cppa_slack_transcript_tracker (huddle transcript, token extraction)
SLACK_TEAM_ID = (env("SLACK_TEAM_ID", default="") or "").strip()
# Internal session tokens (xoxc/xoxd) are ToS-sensitive; only read when explicitly opted in.
_allow_internal_slack_tokens = (
    env("ALLOW_INTERNAL_SLACK_TOKENS", default="") or ""
).strip().lower() == "true"
_xoxc_raw = (env("SLACK_XOXC_TOKEN", default="") or "").strip()
_xoxd_raw = (env("SLACK_XOXD_TOKEN", default="") or "").strip()
if _allow_internal_slack_tokens:
    SLACK_XOXC_TOKEN = _xoxc_raw
    SLACK_XOXD_TOKEN = _xoxd_raw
else:
    SLACK_XOXC_TOKEN = ""
    SLACK_XOXD_TOKEN = ""
    if _xoxc_raw or _xoxd_raw:
        import logging

        logging.getLogger(__name__).warning(
            "SLACK_XOXC_TOKEN/SLACK_XOXD_TOKEN are set but ignored: "
            "internal session tokens require ALLOW_INTERNAL_SLACK_TOKENS=true after compliance review."
        )
# Selenium/Chrome for Slack token extraction (cppa_slack_transcript_tracker)
SELENIUM_HUB_URL = (
    env("SELENIUM_HUB_URL", default="http://localhost:4444/wd/hub") or ""
).strip()
_DEFAULT_CHROME_PROFILE = str(
    WORKSPACE_DIR / "cppa_slack_transcript_tracker" / "chrome_profile"
)
CHROME_PROFILE_PATH = (
    env("CHROME_PROFILE_PATH", default=_DEFAULT_CHROME_PROFILE) or ""
).strip()

# Discord configuration (for discord_activity_tracker)
DISCORD_TOKEN = (env("DISCORD_TOKEN", default="") or "").strip()
DISCORD_USER_TOKEN = (env("DISCORD_USER_TOKEN", default="") or "").strip()
DISCORD_SERVER_ID = (env("DISCORD_SERVER_ID", default="") or "").strip()
DISCORD_CONTEXT_REPO_PATH = Path(
    env(
        "DISCORD_CONTEXT_REPO_PATH",
        default=str(BASE_DIR.parent / "discord-cplusplus-together-context"),
    )
).resolve()

# Logging - project-wide configuration for app commands (console + rotating file)
LOG_DIR = Path(env("LOG_DIR", default=str(BASE_DIR / "logs")))
LOG_FILE = env("LOG_FILE", default="app.log")
LOG_MAX_BYTES = int(env("LOG_MAX_BYTES", default=5 * 1024 * 1024))  # 5 MB
LOG_BACKUP_COUNT = int(env("LOG_BACKUP_COUNT", default=5))
# Log level: use LOG_LEVEL if set (DEBUG, INFO, WARNING, ERROR); else DEBUG when DEBUG=True, else INFO
_log_level_env = (env("LOG_LEVEL", default="") or "").strip().upper()
if _log_level_env in ("DEBUG", "INFO", "WARNING", "ERROR"):
    LOG_LEVEL = _log_level_env
elif DEBUG:
    LOG_LEVEL = "DEBUG"
else:
    LOG_LEVEL = "INFO"
LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE_PATH = LOG_DIR / LOG_FILE

# Error notification settings (Discord/Slack)
ENABLE_ERROR_NOTIFICATIONS = env.bool("ENABLE_ERROR_NOTIFICATIONS", default=False)
DISCORD_WEBHOOK_URL = env("DISCORD_WEBHOOK_URL", default="")
SLACK_WEBHOOK_URL = env("SLACK_WEBHOOK_URL", default="")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name} {module} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(_LOG_FILE_PATH),
            "maxBytes": LOG_MAX_BYTES,
            "backupCount": LOG_BACKUP_COUNT,
            "formatter": "verbose",
            "encoding": "utf-8",
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": LOG_LEVEL,
    },
}

# Celery
CELERY_BROKER_URL = env(
    "CELERY_BROKER_URL",
    default="redis://localhost:6379/0",
)
CELERY_RESULT_BACKEND = env(
    "CELERY_RESULT_BACKEND",
    default=CELERY_BROKER_URL,
)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "America/Los_Angeles"

# Daily at 1:00 AM Pacific (PST/PDT)
CELERY_BEAT_SCHEDULE = {
    "run-all-collectors-daily": {
        "task": "workflow.tasks.run_all_collectors_task",
        "schedule": crontab(hour=1, minute=0),
    },
}

# Conditionally add Discord/Slack handlers for error notifications
if ENABLE_ERROR_NOTIFICATIONS:
    if DISCORD_WEBHOOK_URL:
        LOGGING["handlers"]["discord"] = {
            "class": "config.logging_handlers.DiscordHandler",
            "webhook_url": DISCORD_WEBHOOK_URL,
            "level": "ERROR",
        }
        LOGGING["root"]["handlers"].append("discord")

    if SLACK_WEBHOOK_URL:
        LOGGING["handlers"]["slack"] = {
            "class": "config.logging_handlers.SlackHandler",
            "webhook_url": SLACK_WEBHOOK_URL,
            "level": "ERROR",
        }
        LOGGING["root"]["handlers"].append("slack")
