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
    "github_activity_tracker",
    "boost_library_tracker",
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
_WORKSPACE_APP_SLUGS = ("github_activity_tracker", "boost_library_tracker", "shared")
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
