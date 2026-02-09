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
        "NAME": os.getenv("PORTAL_DB_NAME", "portal_db"),
        "USER": os.getenv("PORTAL_DB_USER", "portal"),
        "PASSWORD": os.getenv("PORTAL_DB_PASSWORD", "portal"),
        "HOST": os.getenv("PORTAL_DB_HOST", "localhost"),
        "PORT": os.getenv("PORTAL_DB_PORT", "5432"),
    },
}

DATABASE_ROUTERS = ["config.db_router.PortalDBRouter"]

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SEMANTIC_MODEL_NAME = os.getenv(
    "SEMANTIC_MODEL_NAME", "paraphrase-multilingual-MiniLM-L12-v2"
)
SEMANTIC_MODEL_PATH = os.getenv("SEMANTIC_MODEL_PATH")
SKIP_SEMANTIC_MODEL = os.getenv("SKIP_SEMANTIC_MODEL", "false").lower() in (
    "1",
    "true",
    "yes",
)
SUBDIVISION_SEMANTIC_THRESHOLD = float(
    os.getenv("SUBDIVISION_SEMANTIC_THRESHOLD", "0.6")
)
