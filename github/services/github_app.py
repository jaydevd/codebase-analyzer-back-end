import hashlib
import hmac
import time
from pathlib import Path
from typing import Any

import jwt
import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from common.constants import GITHUB_BASE_URL


class GitHubAppService:
    """GitHub App authentication and installation helper."""

    def _load_private_key(self) -> bytes:
        if getattr(settings, "GITHUB_PRIVATE_KEY_PATH", ""):
            private_key_path = Path(settings.GITHUB_PRIVATE_KEY_PATH)
            try:
                return private_key_path.read_bytes()
            except OSError as exc:
                raise ImproperlyConfigured(
                    f"Unable to read GitHub private key from path: {private_key_path}: {exc}"
                ) from exc

        raw_key = getattr(settings, "GITHUB_PRIVATE_KEY", "")
        if not raw_key:
            raise ImproperlyConfigured(
                "GITHUB_PRIVATE_KEY or GITHUB_PRIVATE_KEY_PATH must be configured."
            )

        return raw_key.encode("utf-8")

    def generate_app_jwt(self) -> str:
        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + 10 * 60,
            "iss": str(settings.GITHUB_APP_ID),
        }
        private_key = self._load_private_key()
        token = jwt.encode(payload, private_key, algorithm="RS256")
        return token if isinstance(token, str) else token.decode("utf-8")

    def get_installation_token(self, installation_id: int) -> str:
        app_jwt = self.generate_app_jwt()
        response = requests.post(
            f"{GITHUB_BASE_URL}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "Codebase Analyzer",
            },
        )
        response.raise_for_status()
        return response.json()["token"]

    def get_installation_details(self, installation_id: int) -> dict[str, Any]:
        app_jwt = self.generate_app_jwt()
        response = requests.get(
            f"{GITHUB_BASE_URL}/app/installations/{installation_id}",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "Codebase Analyzer",
            },
        )
        response.raise_for_status()
        return response.json()

    def get_installation_repositories(self, installation_id: int) -> list[dict[str, Any]]:
        installation_token = self.get_installation_token(installation_id)
        response = requests.get(
            f"{GITHUB_BASE_URL}/installation/repositories",
            headers={
                "Authorization": f"token {installation_token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "Codebase Analyzer",
            },
            params={"per_page": 100},
        )
        response.raise_for_status()
        return response.json().get("repositories", [])

    @staticmethod
    def verify_webhook_signature(raw_body: bytes, signature_header: str, secret: str) -> bool:
        if not signature_header or not secret:
            return False

        try:
            algorithm, signature = signature_header.split("=", 1)
        except ValueError:
            return False

        if algorithm != "sha256":
            return False

        mac = hmac.new(secret.encode("utf-8"), msg=raw_body, digestmod=hashlib.sha256)
        return hmac.compare_digest(mac.hexdigest(), signature)
