import os

from django.core.exceptions import ImproperlyConfigured

from .base import *


DEBUG = get_bool_env("DEBUG", False)
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ImproperlyConfigured("SECRET_KEY must be set when ENVIRONMENT=production.")

ALLOWED_HOSTS = get_list_env("ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS must be set when ENVIRONMENT=production.")

CSRF_TRUSTED_ORIGINS = get_list_env("CSRF_TRUSTED_ORIGINS")
CORS_ALLOWED_ORIGINS = get_list_env("CORS_ALLOWED_ORIGINS")
SIMPLE_JWT = build_simple_jwt(SECRET_KEY)

SECURE_SSL_REDIRECT = get_bool_env("SECURE_SSL_REDIRECT", True)
SESSION_COOKIE_SECURE = get_bool_env("SESSION_COOKIE_SECURE", True)
CSRF_COOKIE_SECURE = get_bool_env("CSRF_COOKIE_SECURE", True)
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = get_bool_env(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    True,
)
SECURE_HSTS_PRELOAD = get_bool_env("SECURE_HSTS_PRELOAD", True)
