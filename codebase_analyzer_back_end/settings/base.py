import os
import sys
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
import dj_database_url


BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
IS_TEST_RUN = "test" in sys.argv


def get_bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_list_env(name: str, default: str = "") -> list[str]:
    raw_value = os.getenv(name, default)
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def get_env_alias(*names: str, default=None):
    for name in names:
        value = os.getenv(name)
        if value is not None and value != "":
            return value
    return default


def build_simple_jwt(signing_key: str) -> dict:
    return {
        "ACCESS_TOKEN_LIFETIME": timedelta(
            minutes=int(os.getenv("ACCESS_TOKEN_MINUTES", "15"))
        ),
        "REFRESH_TOKEN_LIFETIME": timedelta(
            days=int(os.getenv("REFRESH_TOKEN_DAYS", "7"))
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

database_engine = os.getenv("DB_ENGINE", "django.db.backends.postgresql")
database_url = os.environ.get("DATABASE_URL")
ssl_require = database_engine == "django.db.backends.postgresql"
if database_url and database_url.startswith("sqlite"):
    ssl_require = False

DATABASES = {
    "default": dj_database_url.config(
        default=database_url,
        conn_max_age=600,
        ssl_require=ssl_require,
    )
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
TIME_ZONE = os.getenv("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "auth.User"

if IS_TEST_RUN:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": os.getenv("REDIS_URL", "redis://redis:6379/1"),
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

# EMAIL_BACKEND = get_env_alias(
#     "EMAIL_BACKEND",
#     default=(
#         "django.core.mail.backends.locmem.EmailBackend"
#         if IS_TEST_RUN
#         else "django.core.mail.backends.smtp.EmailBackend"
#     ),
# )
# EMAIL_HOST = get_env_alias("EMAIL_HOST", "SMTP_HOST", default="smtp-relay.brevo.com")
# EMAIL_PORT = int(get_env_alias("EMAIL_PORT", "SMTP_PORT", default="587"))
# EMAIL_HOST_USER = get_env_alias("EMAIL_HOST_USER", "SMTP_USERNAME", default="")
# EMAIL_HOST_PASSWORD = get_env_alias("EMAIL_HOST_PASSWORD", "SMTP_PASSWORD", default="")
# EMAIL_USE_TLS = get_bool_env("EMAIL_USE_TLS", get_bool_env("SMTP_USE_TLS", True))
# EMAIL_USE_SSL = get_bool_env("EMAIL_USE_SSL", get_bool_env("SMTP_USE_SSL", False))
# DEFAULT_FROM_EMAIL = get_env_alias("DEFAULT_FROM_EMAIL", default="no-reply@example.com")
PASSWORD_RESET_FRONTEND_URL = os.getenv(
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

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True

if IS_TEST_RUN:
    PASSWORD_HASHERS = [
        "django.contrib.auth.hashers.MD5PasswordHasher",
    ]

    class DisableMigrations(dict):
        def __contains__(self, item):
            return True

        def __getitem__(self, item):
            return None

    MIGRATION_MODULES = DisableMigrations()
