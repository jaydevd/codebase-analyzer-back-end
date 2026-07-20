import os
from datetime import timedelta
from pathlib import Path
from typing import Optional

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent.parent

def load_dotenv_file(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue

        cleaned_value = value.strip()
        if len(cleaned_value) >= 2 and cleaned_value[0] == cleaned_value[-1] and cleaned_value[0] in {"'", '"'}:
            cleaned_value = cleaned_value[1:-1]
        os.environ[key] = cleaned_value


def get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(name, default)


def get_bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def get_list_env(name: str, default: str = "") -> list[str]:
    raw_value = os.getenv(name, default)
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def get_env_alias(*names: str, default=None):
    for name in names:
        value = os.getenv(name, default)
        if value is not None and value != "":
            return value
    return default


load_dotenv_file(BASE_DIR / ".env")

ENVIRONMENT = get_env("ENVIRONMENT", "development").strip().lower()


def build_simple_jwt(signing_key: str) -> dict:
    return {
        "ACCESS_TOKEN_LIFETIME": timedelta(
            minutes=int(get_env("ACCESS_TOKEN_MINUTES", "15"))
        ),
        "REFRESH_TOKEN_LIFETIME": timedelta(
            days=int(get_env("REFRESH_TOKEN_DAYS", "7"))
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
    "github",
    "embeddings",
    "core",
    "admin_api",
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

DATABASES = {
    "default": {
        "ENGINE": get_env("DB_ENGINE", "django.db.backends.postgresql"),
        "NAME": get_env("DB_NAME", ""),
        "USER": get_env("DB_USER", ""),
        "PASSWORD": get_env("DB_PASSWORD", ""),
        "HOST": get_env("DB_HOST", ""),
        "PORT": get_env("DB_PORT", ""),
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
TIME_ZONE = get_env("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "user_auth.User"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": get_env("REDIS_URL", "redis://redis:6379/1"),
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
PASSWORD_RESET_FRONTEND_URL = get_env(
    "PASSWORD_RESET_FRONTEND_URL",
    "http://localhost:3000/reset-password",
)

GITHUB_APP_ID = get_env("GITHUB_APP_ID", "")
GITHUB_APP_SLUG = get_env("GITHUB_APP_SLUG", "")
GITHUB_PRIVATE_KEY = get_env("GITHUB_PRIVATE_KEY", "")
GITHUB_PRIVATE_KEY_PATH = get_env("GITHUB_PRIVATE_KEY_PATH", "")
GITHUB_WEBHOOK_SECRET = get_env("GITHUB_WEBHOOK_SECRET", "")
FRONTEND_URL = get_env("FRONTEND_URL", "http://localhost:5173")

# OAuth settings
GOOGLE_OAUTH_CLIENT_ID = get_env("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = get_env("GOOGLE_OAUTH_CLIENT_SECRET", "")
GITHUB_OAUTH_CLIENT_ID = get_env("GITHUB_CLIENT_ID", "")
GITHUB_OAUTH_CLIENT_SECRET = get_env("GITHUB_CLIENT_SECRET", "")

SPECTACULAR_SETTINGS = {
    "TITLE": "Codebase Analyzer API",
    "DESCRIPTION": "REST API for indexing, searching, and querying codebases using vector embeddings and LLMs.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": r"/api/",
    "SWAGGER_UI_SETTINGS": {
        "deepLinking": True,
        "persistAuthorization": True,
    },
    "SECURITY": [
        {"Bearer": []},
    ],
    "TAGS": [
        {"name": "Auth", "description": "Authentication, registration, OAuth, and password management"},
        {"name": "Chat", "description": "Chat sessions and codebase querying"},
        {"name": "GitHub", "description": "GitHub repository integration and management"},
        {"name": "Embeddings", "description": "Codebase indexing and embedding"},
        {"name": "Health", "description": "System health checks"},
    ],
}

SIMPLE_JWT = build_simple_jwt(
    get_env(
        "JWT_SIGNING_KEY",
        get_env("SECRET_KEY", "unsafe-development-secret-key-with-32-chars"),
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

CELERY_BROKER_URL = get_env("CELERY_BROKER_URL", get_env("REDIS_URL", "redis://localhost:6379/0"))
CELERY_RESULT_BACKEND = get_env("CELERY_RESULT_BACKEND", get_env("REDIS_URL", "redis://localhost:6379/0"))
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "Asia/Kolkata"
CELERY_WORKER_POOL = "solo"

QDRANT_URL        = os.getenv('QDRANT_URL')
QDRANT_API_KEY    = os.getenv('QDRANT_API_KEY')
QDRANT_COLLECTION = os.getenv('QDRANT_COLLECTION', 'codebase_chunks')

CORS_ALLOW_CREDENTIALS = True

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = "None"

CSRF_COOKIE_SECURE = True
CSRF_COOKIE_SAMESITE = "None"