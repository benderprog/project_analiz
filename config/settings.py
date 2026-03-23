import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-secret-key")
DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.portaldb.apps.PortaldbConfig",
    "apps.classifier.apps.ClassifierConfig",
    "apps.analysis_app.apps.AnalysisAppConfig",
    "apps.users.apps.UsersConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.analysis_app.middleware.PortalDbRuntimeSettingsMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.analysis_app.ui_mode.ui_mode_context",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("APP_DB_NAME", "app_db"),
        "USER": os.getenv("APP_DB_USER", "app"),
        "PASSWORD": os.getenv("APP_DB_PASSWORD", "app"),
        "HOST": os.getenv("APP_DB_HOST", "localhost"),
        "PORT": os.getenv("APP_DB_PORT", "5432"),
    },
    "portal": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("PORTAL_DB_NAME", "portal_db_test"),
        "USER": os.getenv("PORTAL_DB_USER", "portal"),
        "PASSWORD": os.getenv("PORTAL_DB_PASSWORD", "portal"),
        "HOST": os.getenv("PORTAL_DB_HOST", "localhost"),
        "PORT": os.getenv("PORTAL_DB_PORT", "5432"),
    },
}

from apps.portaldb.portal_config import (
    apply_portal_database_settings,
    get_gateway_settings,
    load_portal_config,
)

try:
    portal_cfg, _, _ = load_portal_config(project_root=BASE_DIR)
except FileNotFoundError:
    portal_cfg = None

if portal_cfg and os.getenv("PORTAL_PROFILE"):
    try:
        DATABASES["portal"] = apply_portal_database_settings(globals(), portal_cfg)
    except ValueError as exc:
        raise RuntimeError(f"Portal config error: {exc}") from exc

portal_gateway_settings = {"backend": os.getenv("PORTAL_GATEWAY_BACKEND", "orm"), "alias": "portal"}
if portal_cfg:
    try:
        portal_gateway_settings = get_gateway_settings(portal_cfg)
    except ValueError as exc:
        raise RuntimeError(f"Portal config error: {exc}") from exc

PORTAL_GATEWAY_BACKEND = (
    os.getenv("PORTAL_GATEWAY_BACKEND")
    or portal_gateway_settings["backend"]
    or "orm"
).strip().lower()
PORTAL_DB_ALIAS = portal_gateway_settings["alias"] or "portal"

DATABASE_ROUTERS = ["config.db_router.PortalDBRouter"]

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in ("1", "true", "yes")


SEMANTIC_MODEL_NAME = os.getenv(
    "SEMANTIC_MODEL_NAME", "paraphrase-multilingual-MiniLM-L12-v2"
)
SEMANTIC_MODEL_PATH = os.getenv("SEMANTIC_MODEL_PATH", "")
OFFLINE_MODE = _env_flag("HF_HUB_OFFLINE") or _env_flag("TRANSFORMERS_OFFLINE")
SKIP_SEMANTIC_MODEL = os.getenv("SKIP_SEMANTIC_MODEL", "false").lower() in (
    "1",
    "true",
    "yes",
)
SUBDIVISION_SEMANTIC_THRESHOLD = float(
    os.getenv("SUBDIVISION_SEMANTIC_THRESHOLD", "0.6")
)
SUBDIVISION_ACCEPT_THRESHOLD = float(
    os.getenv("SUBDIVISION_ACCEPT_THRESHOLD", "0.75")
)
SUBDIVISION_LOW_LEXICAL_FACTOR = float(
    os.getenv("SUBDIVISION_LOW_LEXICAL_FACTOR", "0.1")
)
EVENT_PATTERN_SEMANTIC_THRESHOLD = float(
    os.getenv("EVENT_PATTERN_SEMANTIC_THRESHOLD", "0.20")
)
PU_SEMANTIC_THRESHOLD = float(os.getenv("PU_SEMANTIC_THRESHOLD", "0.6"))
MIN_EVENT_PARAGRAPH_CHARS = int(os.getenv("MIN_EVENT_PARAGRAPH_CHARS", "100"))
ANALYSIS_DELETE_UPLOADS = os.getenv("ANALYSIS_DELETE_UPLOADS", "1") == "1"
ANALYSIS_TASK_SOFT_TIME_LIMIT = int(os.getenv("ANALYSIS_TASK_SOFT_TIME_LIMIT", os.getenv("WORKER_SOFT_TIME_LIMIT", "1800")))
ANALYSIS_TASK_TIME_LIMIT = int(os.getenv("ANALYSIS_TASK_TIME_LIMIT", os.getenv("WORKER_TIME_LIMIT", "1860")))
ANALYSIS_DEBUG_TEXT_MAX_CHARS = int(os.getenv("ANALYSIS_DEBUG_TEXT_MAX_CHARS", "20000"))
ANALYSIS_ANCHOR_FALLBACK_FULL_REPORT_MAX_ELEMENTS = int(os.getenv("ANALYSIS_ANCHOR_FALLBACK_FULL_REPORT_MAX_ELEMENTS", "1200"))

CLASSIFIER_TOP_K = int(os.getenv("CLASSIFIER_TOP_K", "5"))
CLASSIFIER_MIN_SCORE = float(os.getenv("CLASSIFIER_MIN_SCORE", "0.5"))
CLASSIFIER_MAX_TEXT_CHARS = int(os.getenv("CLASSIFIER_MAX_TEXT_CHARS", "800"))
CLASSIFIER_SIMILAR_PATTERN_MIN_SCORE = float(os.getenv("CLASSIFIER_SIMILAR_PATTERN_MIN_SCORE", "0.5"))
CLASSIFIER_SIMILAR_PATTERN_LIMIT = int(os.getenv("CLASSIFIER_SIMILAR_PATTERN_LIMIT", "20"))

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_ROUTES = {"apps.analysis_app.tasks.run_docx_analysis": {"queue": "analysis"}}
