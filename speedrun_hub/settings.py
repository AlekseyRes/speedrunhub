"""Django settings for the Speedrun Hub project.

Configuration is read from environment variables (and an optional ``.env``
file) through django-environ. Safe defaults keep local development painless
while every sensitive value stays configurable.
"""

from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["127.0.0.1", "localhost"]),
    DJANGO_SECRET_KEY=(str, ""),
    SPEEDRUN_API_BASE_URL=(str, "https://www.speedrun.com/api/v1"),
    SPEEDRUN_API_KEY=(str, ""),
    SPEEDRUN_API_TIMEOUT=(float, 10.0),
    SPEEDRUN_CACHE_TTL=(int, 300),
    SPEEDRUN_USER_AGENT=(
        str,
        "SpeedrunHub/1.0 (Django demo; +https://www.speedrun.com)",
    ),
)

# Load .env when present. Never commit this file. Existing environment
# variables take precedence over values in .env.
environ.Env.read_env(BASE_DIR / ".env")

DEBUG = env("DJANGO_DEBUG")

# Never fall back to a known secret when DEBUG is off. The insecure fallback
# exists only to keep local development painless.
SECRET_KEY = (env("DJANGO_SECRET_KEY") or "").strip()
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set to a strong, unique value when "
            "DJANGO_DEBUG is False."
        )
    SECRET_KEY = "django-insecure-local-development-only-change-me"

ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
    "accounts",
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

ROOT_URLCONF = "speedrun_hub.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

WSGI_APPLICATION = "speedrun_hub.wsgi.application"
ASGI_APPLICATION = "speedrun_hub.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Authentication flow.
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "core:home"

# In-memory cache is fine for a single-process demo. Swap for Redis/Memcached
# in production so cached API responses survive restarts and scale across
# workers.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "speedrun-hub-cache",
    }
}

# Speedrun.com API client configuration.
SPEEDRUN_API_BASE_URL = env("SPEEDRUN_API_BASE_URL")
SPEEDRUN_API_KEY = env("SPEEDRUN_API_KEY")
SPEEDRUN_API_TIMEOUT = env("SPEEDRUN_API_TIMEOUT")
SPEEDRUN_CACHE_TTL = env("SPEEDRUN_CACHE_TTL")
SPEEDRUN_USER_AGENT = env("SPEEDRUN_USER_AGENT")

# Security hardening. Defaults are safe for production (DEBUG=False) and
# relaxed for local development (DEBUG=True). Every value can be overridden
# from the environment so deployments behind a TLS-terminating proxy can tune
# them without code changes.
SECURE_SSL_REDIRECT = env.bool(
    "DJANGO_SECURE_SSL_REDIRECT", default=not DEBUG
)
SESSION_COOKIE_SECURE = env.bool(
    "DJANGO_SESSION_COOKIE_SECURE", default=not DEBUG
)
CSRF_COOKIE_SECURE = env.bool(
    "DJANGO_CSRF_COOKIE_SECURE", default=not DEBUG
)
SECURE_HSTS_SECONDS = env.int(
    "DJANGO_SECURE_HSTS_SECONDS", default=0 if DEBUG else 31536000
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=not DEBUG
)
SECURE_HSTS_PRELOAD = env.bool(
    "DJANGO_SECURE_HSTS_PRELOAD", default=not DEBUG
)
SECURE_CONTENT_TYPE_NOSNIFF = env.bool(
    "DJANGO_SECURE_CONTENT_TYPE_NOSNIFF", default=True
)
SECURE_REFERRER_POLICY = env(
    "DJANGO_SECURE_REFERRER_POLICY", default="same-origin"
)

# Only trust proxy SSL headers when explicitly configured, e.g.
# DJANGO_SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https
_proxy_ssl_header = (env("DJANGO_SECURE_PROXY_SSL_HEADER", default="") or "").strip()
if _proxy_ssl_header:
    _parts = [part.strip() for part in _proxy_ssl_header.split(",")]
    if len(_parts) != 2 or not all(_parts):
        raise ImproperlyConfigured(
            "DJANGO_SECURE_PROXY_SSL_HEADER must be in the form "
            "'HEADER_NAME,header-value'."
        )
    SECURE_PROXY_SSL_HEADER = (_parts[0], _parts[1])
else:
    SECURE_PROXY_SSL_HEADER = None

CSRF_COOKIE_HTTPONLY = False
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
