"""
Django settings for the Game of Go.

Configuration is driven entirely by environment variables. ``.env.example``
documents the knobs; production on dokku sets them via ``dokku config:set``.
"""

from pathlib import Path

import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'
BASE_DIR = Path(__file__).resolve().parent.parent

# Initialize environment variables
env = environ.Env(DEBUG=(bool, False))

# Read .env file, if it exists
environ.Env.read_env(BASE_DIR / ".env")

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-do-not-use-in-prod")  # type: ignore

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env.bool("DEBUG")  # type: ignore

# When True, every request is short-circuited to a maintenance page (HTTP 503).
MAINTENANCE_MODE = env.bool("MAINTENANCE_MODE", default=False)  # type: ignore

BASE_URL: str = env("BASE_URL", default="http://localhost:8000")  # type: ignore
ORIGIN = BASE_URL.replace("http://", "").replace("https://", "").split(":")[0]
CSRF_TRUSTED_ORIGINS = [BASE_URL]
ALLOWED_HOSTS = [ORIGIN, "localhost", "127.0.0.1"]
INTERNAL_IPS = ["127.0.0.1"]

INSTALLED_APPS = [
    *([] if DEBUG else ["servestatic.runserver_nostatic"]),
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "go.game",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "go.middleware.MaintenanceModeMiddleware",
    *([] if DEBUG else ["servestatic.middleware.ServeStaticMiddleware"]),
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "go.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "go" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "go.wsgi.application"

# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases


# Use Postgres in production; SQLite for local dev if DATABASE_URL is not set
DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")  # type: ignore
}

if (
    env.bool("DATABASE_DISABLE_SSL", default=False)
    and DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"
):
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"]["sslmode"] = "disable"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/Los_Angeles"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATICFILES_DIRS = [BASE_DIR / "go" / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STATIC_URL = "static/"

# Enable ServeStatic's GZip compression of static assets (production only).
if not DEBUG:
    STORAGES = {
        "staticfiles": {"BACKEND": "servestatic.storage.CompressedManifestStaticFilesStorage"}
    }

# Email configuration

EMAIL_HOST = env("EMAIL_HOST", default="localhost")  # type: ignore
EMAIL_PORT = env.int("EMAIL_PORT", default=25)  # type: ignore
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")  # type: ignore
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")  # type: ignore
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)  # type: ignore
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)  # type: ignore
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",  # type: ignore
)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="go@example.com").strip()  # type: ignore
SERVER_EMAIL = env("SERVER_EMAIL", default="admin@example.com").strip()  # type: ignore
ADMINS = env.json("ADMINS", default=[["Go Admin", "admin@example.com"]])  # type: ignore


# Logging

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "timestamped": {
            "format": "%(asctime)s %(levelname)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "timestamped",
        },
    },
    "loggers": {
        "cookie.trails": {
            "handlers": ["console"],
            "level": "INFO",
        },
    },
}


# Background tasks

TASKS = {
    "default": {
        "BACKEND": "django.tasks.backends.immediate.ImmediateBackend",
    }
}
