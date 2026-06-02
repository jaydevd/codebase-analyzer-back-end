import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from auth.utils import build_password_reset_url

logger = logging.getLogger(__name__)


class AuthEmailService:
    @staticmethod
    def _send_email(*, subject, template_prefix, to_email, context):
        text_body = render_to_string(f"auth/emails/{template_prefix}.txt", context)
        html_body = render_to_string(f"auth/emails/{template_prefix}.html", context)
        message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to_email],
        )
        message.attach_alternative(html_body, "text/html")
        try:
            return bool(message.send(fail_silently=False))
        except Exception:
            logger.exception(
                "Failed to send auth email.",
                extra={
                    "template_prefix": template_prefix,
                    "to_email": to_email,
                    "from_email": settings.DEFAULT_FROM_EMAIL,
                },
            )
            return False

    @classmethod
    def send_welcome_email(cls, user):
        return cls._send_email(
            subject="Welcome to Codebase Analyzer",
            template_prefix="welcome",
            to_email=user.email,
            context={"user": user},
        )

    @classmethod
    def send_password_changed_email(cls, user):
        return cls._send_email(
            subject="Your password was changed",
            template_prefix="password_changed",
            to_email=user.email,
            context={"user": user},
        )

    @classmethod
    def send_password_reset_email(cls, user):
        token = default_token_generator.make_token(user)
        reset_url = build_password_reset_url(user, token)
        return cls._send_email(
            subject="Reset your password",
            template_prefix="password_reset",
            to_email=user.email,
            context={"user": user, "reset_url": reset_url, "token": token},
        )
