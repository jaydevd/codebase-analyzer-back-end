import os
import sys
from datetime import timedelta
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(str(BASE_DIR / ".env"))

ENVIRONMENT = env.str("ENVIRONMENT", "development").strip().lower()

def get_bool_env(name: str, default: bool = False) -> bool:
    value = env.bool(name, default)
    return value

def get_list_env(name: str, default: str = "") -> list[str]:
    raw_value = env.str(name, default)
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def get_env_alias(*names: str, default=None):
    for name in names:
        value = env.str(name, default)
        if value is not None and value != "":
            return value
    return default


def build_simple_jwt(signing_key: str) -> dict:
    return {
        "ACCESS_TOKEN_LIFETIME": timedelta(
            minutes=int(env.str("ACCESS_TOKEN_MINUTES", "15"))
        ),
        "REFRESH_TOKEN_LIFETIME": timedelta(
            days=int(env.str("REFRESH_TOKEN_DAYS", "7"))
        ),
        "ROTATE_REFRESH_TOKENS": True,
        "BLACKLIST_AFTER_ROTATION": True,
        "UPDATE_LAST_LOGIN": True,
        "ALGORITHM": "HS256",
        "SIGNING_KEY": signing_key,
        "AUTH_HEADER_TYPES": ("Bearer",),
        "USER_ID_FIELD": "id",
        "USER_ID_CLAIM": "user_id",
    }


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "common",
    "auth.apps.AuthConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "codebase_analyzer_back_end.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

WSGI_APPLICATION = "codebase_analyzer_back_end.wsgi.application"
ASGI_APPLICATION = "codebase_analyzer_back_end.asgi.application"

# database_engine = env.str("DB_ENGINE", "django.db.backends.postgresql")
# database_url = env.str("DATABASE_URL")
# ssl_require = database_engine == "django.db.backends.postgresql"
# if database_url and database_url.startswith("sqlite"):
#     ssl_require = False
print("db name:", env.str("DB_NAME", ""))
DATABASES = {
    "default": {
        "ENGINE": env.str("DB_ENGINE", "django.db.backends.postgresql"),
        "NAME": env.str("DB_NAME", ""),
        "USER": env.str("DB_USER", ""),
        "PASSWORD": env.str("DB_PASSWORD", ""),
        "HOST": env.str("DB_HOST", ""),
        "PORT": env.str("DB_PORT", ""),
        "OPTIONS": {"sslmode": "require"},
    }
}

if DATABASES["default"].get("ENGINE") in ["django.db.backends.postgresql", "django.db.backends.postgis"]:
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"]["options"] = "-c search_path=public"


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = env.str("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "user_auth.User"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env.str("REDIS_URL", "redis://redis:6379/1"),
        "TIMEOUT": 300,
    }
}

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "common.pagination.StandardResultsSetPagination",
    "PAGE_SIZE": 10,
    # "EXCEPTION_HANDLER": "codebase_analyzer_back_end.exceptions.custom_exception_handler",
}

EMAIL_HOST = get_env_alias("EMAIL_HOST", default="smtp-relay.brevo.com")
EMAIL_PORT = int(get_env_alias("EMAIL_PORT", default="587"))
EMAIL_HOST_USER = get_env_alias("EMAIL_HOST_USER", "BREVO_SMTP_USERNAME", default="")
EMAIL_HOST_PASSWORD = get_env_alias(
    "EMAIL_HOST_PASSWORD",
    "BREVO_SMTP_PASSWORD",
    default="",
)
EMAIL_USE_TLS = get_bool_env("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = get_bool_env("EMAIL_USE_SSL", False)
DEFAULT_EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
if ENVIRONMENT == "development" and not (EMAIL_HOST_USER and EMAIL_HOST_PASSWORD):
    DEFAULT_EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

EMAIL_BACKEND = get_env_alias("EMAIL_BACKEND", default=DEFAULT_EMAIL_BACKEND)
if (
    EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend"
    and (not EMAIL_HOST_USER or not EMAIL_HOST_PASSWORD)
):
    raise ImproperlyConfigured(
        "SMTP email requires credentials. Set EMAIL_HOST_USER/EMAIL_HOST_PASSWORD "
        "or BREVO_SMTP_USERNAME/BREVO_SMTP_PASSWORD."
    )

DEFAULT_FROM_EMAIL = get_env_alias(
    "DEFAULT_FROM_EMAIL",
    default=EMAIL_HOST_USER or "no-reply@example.com",
)
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_TIMEOUT = int(get_env_alias("EMAIL_TIMEOUT", default="30"))
PASSWORD_RESET_FRONTEND_URL = env.str(
    "PASSWORD_RESET_FRONTEND_URL",
    "http://localhost:3000/reset-password",
)

SPECTACULAR_SETTINGS = {
    "TITLE": "Product And Order Management API",
    "DESCRIPTION": "Production-ready Django REST Framework API for users, products, and orders.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

SIMPLE_JWT = build_simple_jwt(
    env.str(
        "JWT_SIGNING_KEY",
        env.str("SECRET_KEY", "unsafe-development-secret-key-with-32-chars"),
    )
)

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True

# if IS_TEST_RUN:
#     PASSWORD_HASHERS = [
#         "django.contrib.auth.hashers.MD5PasswordHasher",
#     ]

#     class DisableMigrations(dict):
#         def __contains__(self, item):
#             return True

#         def __getitem__(self, item):
#             return None

#     MIGRATION_MODULES = DisableMigrations()
