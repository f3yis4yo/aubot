"""Django settings for AUBOT.

Everything environment-specific is read from environment variables (or the
repo-root .env file in development) so the same image runs locally, in CI and
on any cloud host.
"""
import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent
load_dotenv(REPO_ROOT / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(int(default))).lower() in {"1", "true", "yes", "on"}


DEBUG = env_bool("DJANGO_DEBUG")
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or ("dev-insecure-key" if DEBUG else None)
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off")

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:5173").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels",
    "core",
    "chat",
    "documents",
    "buddy",
    "evaluation",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=60, conn_health_checks=True
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REDIS_URL = os.environ.get("REDIS_URL")
if REDIS_URL:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {"hosts": [REDIS_URL]}}}
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}
else:  # single-process fallback for tests / quick demos
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en-au"
TIME_ZONE = "Australia/Sydney"
USE_I18N = True
USE_TZ = True

# Static files: the built React app (frontend/dist) is served by WhiteNoise so
# the whole product deploys as one service.
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
STATICFILES_DIRS = [FRONTEND_DIST] if FRONTEND_DIST.exists() else []
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
WHITENOISE_USE_FINDERS = DEBUG  # serve frontend/dist without collectstatic during development
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
MEDIA_URL = "/media/"  # never routed publicly; staff download through the API

# Uploads stay in memory only (documents are capped at 5 MB and voice clips are
# small), so raw voice audio never touches the disk (APP 11 / Assessment 1).
FILE_UPLOAD_HANDLERS = ["django.core.files.uploadhandler.MemoryFileUploadHandler"]
FILE_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

# ---------------------------------------------------------------------------
# AUBOT behaviour. Defaults follow Assessments 1 and 2; each can be overridden
# per deployment without code changes.
# ---------------------------------------------------------------------------
AUBOT = {
    # UC01/UC03: below this intent confidence the bot may only answer from the FAQ, else it escalates.
    "CONFIDENCE_THRESHOLD": float(os.environ.get("AUBOT_CONFIDENCE_THRESHOLD", "0.6")),
    # "local" (embeddings + logistic regression, free, reproducible), "tfidf" (lighter,
    # less accurate) or "dialogflow" (needs GCP credentials). See chat/nlu/local.py.
    "INTENT_BACKEND": os.environ.get("AUBOT_INTENT_BACKEND", "local"),
    "DIALOGFLOW_PROJECT_ID": os.environ.get("DIALOGFLOW_PROJECT_ID", ""),
    "DIALOGFLOW_LANGUAGE": os.environ.get("DIALOGFLOW_LANGUAGE", "en-AU"),
    # "vader" (default, ~1 MB) or "hf" (Hugging Face transformers; needs requirements-hf.txt and ~2 GB RAM).
    "SENTIMENT_BACKEND": os.environ.get("AUBOT_SENTIMENT_BACKEND", "vader"),
    "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
    "OPENAI_MODEL": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
    "OPENAI_TRANSCRIBE_MODEL": os.environ.get("OPENAI_TRANSCRIBE_MODEL", "whisper-1"),
    "OPENAI_TTS_MODEL": os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
    "OPENAI_TIMEOUT_SECONDS": float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "12")),
    # Hard spend cap (contingency rule in Assessment 2, Section 6): once reached,
    # generative answers are skipped (the bot escalates) and voice is disabled.
    "MONTHLY_BUDGET_USD": float(os.environ.get("AUBOT_MONTHLY_BUDGET_USD", "20")),
    "MAX_UPLOAD_BYTES": int(float(os.environ.get("AUBOT_MAX_UPLOAD_MB", "5")) * 1024 * 1024),
    "MAX_AUDIO_BYTES": 3 * 1024 * 1024,
    "RATE_LIMIT_PER_MINUTE": int(os.environ.get("AUBOT_RATE_LIMIT_PER_MINUTE", "30")),  # messages per chat
    "SESSION_RATE_LIMIT_PER_MINUTE": int(os.environ.get("AUBOT_SESSION_RATE_LIMIT_PER_MINUTE", "20")),  # new chats per IP
    "RETENTION_DAYS": int(os.environ.get("AUBOT_RETENTION_DAYS", "90")),
    "DATA_DIR": BASE_DIR / "data",
}
