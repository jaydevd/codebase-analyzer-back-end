from django.conf import settings
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes


def build_password_reset_url(user, token):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    base_url = settings.PASSWORD_RESET_FRONTEND_URL.rstrip("/")
    return f"{base_url}/{uid}/{token}"
