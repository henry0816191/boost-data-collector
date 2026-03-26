"""
Django settings for Boost Data Collector project.
Uses django-environ for environment variables.
"""

from pathlib import Path

import environ


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

# Reverse proxy (e.g. nginx terminating TLS). Enable USE_TLS_PROXY_HEADERS only behind a trusted proxy.
USE_X_FORWARDED_HOST = env.bool("USE_X_FORWARDED_HOST", default=False)
if env.bool("USE_TLS_PROXY_HEADERS", default=False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

_static_url = (env("STATIC_URL", default="static/") or "static/").strip()
if _static_url and not _static_url.endswith("/"):
    _static_url += "/"
STATIC_URL = _static_url

_force_script_name = (env("FORCE_SCRIPT_NAME", default="") or "").strip()
if _force_script_name:
    FORCE_SCRIPT_NAME = _force_script_name

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    # Project apps (github_ops before github_activity_tracker - tracker depends on ops)
    "core",
    "workflow",
    "boost_collector_runner",  # YAML-driven schedule; run_scheduled_collectors
    "cppa_user_tracker",
    "github_ops",
    "operations",
    "github_activity_tracker",
    "boost_library_tracker",
    "boost_library_docs_tracker",
    "boost_library_usage_dashboard",
    "boost_usage_tracker",
    "boost_mailing_list_tracker",
    "cppa_pinecone_sync",
    "clang_github_tracker",
    "cppa_slack_tracker",
    "discord_activity_tracker",
    "slack_event_handler",
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

# Static files (STATIC_URL set above from env; STATIC_ROOT is collectstatic output)
STATIC_ROOT = BASE_DIR / "staticfiles"

# Workspace: one folder for raw/processed files, subfolders per app (see docs/Workspace.md)
WORKSPACE_DIR = Path(
    env("WORKSPACE_DIR", default=str(BASE_DIR / "workspace"))
).resolve()
# Raw: unprocessed fetch output (e.g. raw/cppa_slack_tracker/<team_id>/<channel_id>/YYYY-MM-DD.json)
_raw_dir_env = (env("RAW_DIR", default="") or "").strip()
RAW_DIR = Path(_raw_dir_env or str(WORKSPACE_DIR / "raw")).resolve()
RAW_DIR.mkdir(parents=True, exist_ok=True)
_WORKSPACE_APP_SLUGS = (
    "github_activity_tracker",
    "boost_library_tracker",
    "boost_library_docs_tracker",
    "boost_library_usage_dashboard",
    "boost_usage_tracker",
    "cppa_slack_tracker",
    "discord_activity_tracker",
    "boost_mailing_list_tracker",
    "shared",
)
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
for _slug in _WORKSPACE_APP_SLUGS:
    (WORKSPACE_DIR / _slug).mkdir(parents=True, exist_ok=True)

# =============================================================================
# Clang GitHub Tracker
# Syncs llvm/llvm-project (issues, PRs, commits) to raw workspace only (no DB).
# After sync, updated issues/PRs are exported as Markdown and pushed to the
# private repo below. If OWNER or NAME is not set, upload is skipped and an
# error is logged.
# Folder structure: issues/YYYY/YYYY-MM/#N - title.md  (no repo prefix)
# =============================================================================
# Boost GitHub owner (used by boost_library_tracker preprocessors for Pinecone sync)
BOOST_GITHUB_OWNER = (
    env("BOOST_GITHUB_OWNER", default="boostorg") or "boostorg"
).strip() or "boostorg"

# Pinecone (cppa_pinecone_sync) — read from .env
# Public API key (used when --pinecone-instance=public or unset)
PINECONE_API_KEY = (env("PINECONE_API_KEY", default="") or "").strip()
# Private API key (used when --pinecone-instance=private)
PINECONE_PRIVATE_API_KEY = (env("PINECONE_PRIVATE_API_KEY", default="") or "").strip()
PINECONE_INDEX_NAME = (
    env("PINECONE_INDEX_NAME", default="") or ""
).strip() or "boost-dashboard"
PINECONE_ENVIRONMENT = (
    env("PINECONE_ENVIRONMENT", default="us-east-1") or "us-east-1"
).strip() or "us-east-1"
PINECONE_CLOUD = (env("PINECONE_CLOUD", default="aws") or "aws").strip() or "aws"
# Chunking and batching
PINECONE_BATCH_SIZE = env.int("PINECONE_BATCH_SIZE", default=96)
PINECONE_CHUNK_SIZE = env.int("PINECONE_CHUNK_SIZE", default=1000)
PINECONE_CHUNK_OVERLAP = env.int("PINECONE_CHUNK_OVERLAP", default=200)
PINECONE_MIN_TEXT_LENGTH = env.int("PINECONE_MIN_TEXT_LENGTH", default=50)
PINECONE_MIN_WORDS = env.int("PINECONE_MIN_WORDS", default=5)
# Embedding models (Pinecone integrated embeddings)
PINECONE_DENSE_MODEL = (
    env("PINECONE_DENSE_MODEL", default="multilingual-e5-large")
    or "multilingual-e5-large"
).strip() or "multilingual-e5-large"
PINECONE_SPARSE_MODEL = (
    env("PINECONE_SPARSE_MODEL", default="pinecone-sparse-english-v0")
    or "pinecone-sparse-english-v0"
).strip() or "pinecone-sparse-english-v0"

# Pinecone sync: app_type and namespace per app (used when CLI does not pass --pinecone-app-type/--pinecone-namespace)
# Boost Mailing List Tracker
BOOST_MAILING_LIST_PINECONE_APP_TYPE = (
    env("BOOST_MAILING_LIST_PINECONE_APP_TYPE", default="mailing") or "mailing"
).strip() or "mailing"
BOOST_MAILING_LIST_PINECONE_NAMESPACE = (
    env("BOOST_MAILING_LIST_PINECONE_NAMESPACE", default="mailing") or "mailing"
).strip() or "mailing"
# Boost Library Tracker (GitHub issues/PRs)
BOOST_GITHUB_PINECONE_APP_TYPE = (
    env("BOOST_GITHUB_PINECONE_APP_TYPE", default="github-boostorg")
    or "github-boostorg"
).strip() or "github-boostorg"
BOOST_GITHUB_PINECONE_NAMESPACE = (
    env("BOOST_GITHUB_PINECONE_NAMESPACE", default="github-boostorg")
    or "github-boostorg"
).strip() or "github-boostorg"
# Clang GitHub Tracker (GitHub issues/PRs)
CLANG_GITHUB_PINECONE_APP_TYPE = (
    env("CLANG_GITHUB_PINECONE_APP_TYPE", default="github-clang") or "github-clang"
).strip() or "github-clang"
CLANG_GITHUB_PINECONE_NAMESPACE = (
    env("CLANG_GITHUB_PINECONE_NAMESPACE", default="github-clang") or "github-clang"
).strip() or "github-clang"

# Clang GitHub Tracker (raw sync: commits, issues, PRs for one repo)
CLANG_GITHUB_OWNER = (
    env("CLANG_GITHUB_OWNER", default="llvm") or "llvm"
).strip() or "llvm"
CLANG_GITHUB_REPO = (
    env("CLANG_GITHUB_REPO", default="llvm-project") or "llvm-project"
).strip() or "llvm-project"
CLANG_GITHUB_TRACKER_PRIVATE_REPO_OWNER = (
    env("CLANG_GITHUB_TRACKER_PRIVATE_REPO_OWNER", default="") or ""
).strip()
CLANG_GITHUB_TRACKER_PRIVATE_REPO_NAME = (
    env("CLANG_GITHUB_TRACKER_PRIVATE_REPO_NAME", default="") or ""
).strip()
CLANG_GITHUB_TRACKER_PRIVATE_REPO_BRANCH = (
    env("CLANG_GITHUB_TRACKER_PRIVATE_REPO_BRANCH", default="main") or "main"
).strip()

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

# =============================================================================
# Boost Library Tracker
# Syncs boostorg/boost + all submodules (issues, PRs, commits) to DB.
# After sync, updated issues/PRs are exported as Markdown and pushed to the
# repo below. If OWNER or NAME is not set, upload is skipped and an error is
# logged.
# Folder structure: boost/issues/YYYY/YYYY-MM/#N - title.md        (main repo)
#                   boost.<submodule>/issues/YYYY/YYYY-MM/#N - title.md
# =============================================================================
BOOST_LIBRARY_TRACKER_REPO_OWNER = (
    env("BOOST_LIBRARY_TRACKER_REPO_OWNER", default="") or ""
).strip()
BOOST_LIBRARY_TRACKER_REPO_NAME = (
    env("BOOST_LIBRARY_TRACKER_REPO_NAME", default="") or ""
).strip()
BOOST_LIBRARY_TRACKER_REPO_BRANCH = (
    env("BOOST_LIBRARY_TRACKER_REPO_BRANCH", default="master") or "master"
).strip()

# Settings for publishing boost_library_usage_dashboard
BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_OWNER = (
    env("BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_OWNER", default="") or ""
).strip()
BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_REPO = (
    env("BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_REPO", default="") or ""
).strip()
BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_TOKEN = (
    env("BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_TOKEN", default="") or ""
).strip() or GITHUB_TOKEN_WRITE
BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_BRANCH = (
    env("BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_BRANCH", default="") or ""
).strip()


# Slack (bot + app token for operations.slack_ops and cppa_slack_transcript_tracker)
# SLACK_BOT_TOKEN: built from env (prefixed vars). In settings it is a dict (team_id -> token).
# Env: SLACK_TEAM_IDS=id1,id2 and SLACK_BOT_TOKEN_id1=xoxb-..., etc.

SLACK_TEAM_ID = (env("SLACK_TEAM_ID", default="") or "").strip()


def _slack_bot_token_from_env():
    """Build a dict of team_id -> bot token from SLACK_TEAM_IDS and SLACK_BOT_TOKEN_<id> env vars."""
    out = {}
    ids_raw = (env("SLACK_TEAM_IDS", default="") or "").strip()
    if not ids_raw:
        return out
    for tid in ids_raw.split(","):
        tid = tid.strip()
        if not tid:
            continue
        key = f"SLACK_BOT_TOKEN_{tid}"
        token = (env(key, default="") or "").strip()
        if token:
            out[tid] = token
    return out


SLACK_BOT_TOKEN = _slack_bot_token_from_env()


def _slack_app_token_from_env():
    """Build a dict of team_id -> app token from SLACK_TEAM_IDS and SLACK_APP_TOKEN_<id> env vars."""
    out = {}
    ids_raw = (env("SLACK_TEAM_IDS", default="") or "").strip()
    if not ids_raw:
        return out
    for tid in ids_raw.split(","):
        tid = tid.strip()
        if not tid:
            continue
        key = f"SLACK_APP_TOKEN_{tid}"
        token = (env(key, default="") or "").strip()
        if token:
            out[tid] = token
    return out


SLACK_APP_TOKEN = _slack_app_token_from_env()


def _slack_team_scope_from_env():
    """
    Build a dict of team_id -> list of scope ints from SLACK_TEAM_IDS and
    SLACK_TEAM_SCOPE_<id> env vars. Scope: 0 = huddle support, 1 = PR bot.
    Value is comma-separated, e.g. "0", "1", "0, 1". Invalid entries are skipped.
    If SLACK_TEAM_SCOPE_<id> is missing or empty, that team gets [0, 1] (both).
    """
    out = {}
    ids_raw = (env("SLACK_TEAM_IDS", default="") or "").strip()
    if not ids_raw:
        return out
    valid_scopes = {0, 1}
    for tid in ids_raw.split(","):
        tid = tid.strip()
        if not tid:
            continue
        key = f"SLACK_TEAM_SCOPE_{tid}"
        raw = (env(key, default="") or "").strip()
        if not raw:
            out[tid] = [0, 1]
            continue
        scopes = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                n = int(part)
                if n in valid_scopes:
                    scopes.append(n)
            except (ValueError, TypeError):
                continue
        out[tid] = scopes if scopes else [0, 1]

    return out


SLACK_TEAM_SCOPE = _slack_team_scope_from_env()
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

# Slack PR Bot configuration (for slack_event_handler)
SLACK_PR_BOT_TEAM = (env("SLACK_PR_BOT_TEAM", default="") or "").strip()
SLACK_PR_BOT_GITHUB_TOKEN = (env("SLACK_PR_BOT_GITHUB_TOKEN", default="") or "").strip()
SLACK_PR_BOT_CHANNEL_NAME = (
    env("SLACK_PR_BOT_CHANNEL_NAME", default="slack-bot") or "slack-bot"
).strip()
SLACK_PR_BOT_COMMENT_TEMPLATE = (
    env(
        "SLACK_PR_BOT_COMMENT_TEMPLATE",
        default="Automated comment from Slack bot.",
    )
    or ""
).strip() or "Automated comment from Slack bot."
SLACK_PR_BOT_COMMENTS_MAX_PER_WINDOW = int(
    env("SLACK_PR_BOT_COMMENTS_MAX_PER_WINDOW", default="5") or "5"
)
SLACK_PR_BOT_COMMENTS_WINDOW_SECONDS = int(
    env("SLACK_PR_BOT_COMMENTS_WINDOW_SECONDS", default="3600") or "3600"
)

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
            "class": "config.logging_handlers.SafeRotatingFileHandler",
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
    "loggers": {
        # Celery internals (bootsteps, timer, consumer) are noisy at DEBUG; use INFO only then.
        "celery": {
            "level": "INFO" if LOG_LEVEL == "DEBUG" else LOG_LEVEL,
            "propagate": True,
        },
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
# CELERY_TIMEZONE = "America/Los_Angeles"
CELERY_ENABLE_UTC = True  # Beat schedule times (default_time from YAML) are UTC

# Schedule from YAML (boost_collector_runner); on load error fall back to empty beat schedule ({})
BOOST_COLLECTOR_SCHEDULE_YAML = BASE_DIR / "config" / "boost_collector_schedule.yaml"
try:
    from boost_collector_runner.schedule_config import get_beat_schedule

    CELERY_BEAT_SCHEDULE = get_beat_schedule()
except Exception:
    import logging

    logging.getLogger(__name__).exception(
        "Could not load boost collector schedule from YAML.",
    )
    CELERY_BEAT_SCHEDULE = {}

# =============================================================================
# Pinecone (cppa_pinecone_sync) - vector index for RAG sync
# =============================================================================
# Public API key (default). Used when instance=public or unset.
PINECONE_API_KEY = (env("PINECONE_API_KEY", default="") or "").strip()
# Private API key. Used when instance=private.
PINECONE_PRIVATE_API_KEY = (env("PINECONE_PRIVATE_API_KEY", default="") or "").strip()
# Index name (required for sync). Set in .env to enable Slack/mailing list → Pinecone.
PINECONE_INDEX_NAME = (env("PINECONE_INDEX_NAME", default="") or "").strip()
PINECONE_ENVIRONMENT = (
    env("PINECONE_ENVIRONMENT", default="us-east-1") or "us-east-1"
).strip()
PINECONE_CLOUD = (env("PINECONE_CLOUD", default="aws") or "aws").strip()
PINECONE_BATCH_SIZE = int(env("PINECONE_BATCH_SIZE", default="96") or "96")
PINECONE_CHUNK_SIZE = int(env("PINECONE_CHUNK_SIZE", default="1000") or "1000")
PINECONE_CHUNK_OVERLAP = int(env("PINECONE_CHUNK_OVERLAP", default="200") or "200")
PINECONE_MIN_TEXT_LENGTH = int(env("PINECONE_MIN_TEXT_LENGTH", default="50") or "50")
PINECONE_MIN_WORDS = int(env("PINECONE_MIN_WORDS", default="5") or "5")
PINECONE_SLACK_NAMESPACE_PREFIX = (
    env("PINECONE_SLACK_NAMESPACE_PREFIX", default="slack") or "slack"
).strip()
PINECONE_SLACK_APP_TYPE_PREFIX = (
    env("PINECONE_SLACK_APP_TYPE_PREFIX", default="slack") or "slack"
).strip()
PINECONE_DENSE_MODEL = (
    env("PINECONE_DENSE_MODEL", default="multilingual-e5-large")
    or "multilingual-e5-large"
).strip()
PINECONE_SPARSE_MODEL = (
    env("PINECONE_SPARSE_MODEL", default="pinecone-sparse-english-v0")
    or "pinecone-sparse-english-v0"
).strip()

# GitHub activity tracker: Redis for ETag cache (conditional GET). Use separate DB index.
# To persist the cache across restarts, enable Redis persistence (RDB or AOF) in redis.conf:
#   RDB: leave default "save" rules (e.g. save 900 1) and set dir/dbfilename.
#   AOF: appendonly yes.
GITHUB_ETAG_REDIS_URL = env(
    "GITHUB_ETAG_REDIS_URL",
    default="redis://localhost:6379/1",
)

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
