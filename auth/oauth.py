import logging
import secrets
from typing import Optional

import requests
from django.conf import settings
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPES = "openid email profile"

GITHUB_BASE_URL = "https://github.com"
GITHUB_API_URL = "https://api.github.com"


class GoogleOAuthService:
    @staticmethod
    def get_authorize_url(state: str, redirect_uri: str) -> str:
        params = {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GOOGLE_SCOPES,
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{GOOGLE_AUTH_URL}?{query}"

    @staticmethod
    def exchange_code_for_token(code: str, redirect_uri: str) -> Optional[dict]:
        try:
            response = requests.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                    "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            logger.warning("Google token exchange failed: %s", exc)
            return None

    @staticmethod
    def verify_id_token(token: str) -> Optional[dict]:
        try:
            info = id_token.verify_oauth2_token(
                token,
                google_requests.Request(),
                settings.GOOGLE_OAUTH_CLIENT_ID,
            )
            if info.get("iss") not in [
                "accounts.google.com",
                "https://accounts.google.com",
            ]:
                raise ValueError("Wrong issuer.")
            return {
                "google_id": info["sub"],
                "email": info.get("email", ""),
                "first_name": info.get("given_name", ""),
                "last_name": info.get("family_name", ""),
                "avatar_url": info.get("picture", ""),
                "email_verified": info.get("email_verified", False),
            }
        except ValueError as exc:
            logger.warning("Google token verification failed: %s", exc)
            return None


class GitHubOAuthService:
    @staticmethod
    def get_authorize_url(state: str, redirect_uri: str) -> str:
        params = {
            "client_id": settings.GITHUB_OAUTH_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": "read:user,user:email,repo",
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{GITHUB_BASE_URL}/login/oauth/authorize?{query}"

    @staticmethod
    def exchange_code_for_token(code: str, redirect_uri: str) -> dict:
        response = requests.post(
            f"{GITHUB_BASE_URL}/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.GITHUB_OAUTH_CLIENT_ID,
                "client_secret": settings.GITHUB_OAUTH_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def get_user_info(access_token: str) -> dict:
        response = requests.get(
            f"{GITHUB_API_URL}/user",
            headers={
                "Authorization": f"token {access_token}",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def get_user_emails(access_token: str) -> list:
        response = requests.get(
            f"{GITHUB_API_URL}/user/emails",
            headers={
                "Authorization": f"token {access_token}",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        return response.json()

    @classmethod
    def get_verified_primary_email(cls, access_token: str, user_info: dict | None = None) -> str | None:
        user_info = user_info or {}
        email = user_info.get("email")
        if email:
            return email

        emails = cls.get_user_emails(access_token)
        primary_email = next(
            (
                entry.get("email")
                for entry in emails
                if entry.get("primary") and entry.get("verified")
            ),
            None,
        )
        if primary_email:
            return primary_email

        return next(
            (entry.get("email") for entry in emails if entry.get("verified")),
            None,
        )

    @staticmethod
    def get_user_repos(access_token: str) -> list:
        response = requests.get(
            f"{GITHUB_API_URL}/user/repos",
            headers={
                "Authorization": f"token {access_token}",
                "Accept": "application/json",
            },
            params={"per_page": 100, "sort": "updated", "direction": "desc"},
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def get_repo(access_token: str, full_name: str) -> dict:
        response = requests.get(
            f"{GITHUB_API_URL}/repos/{full_name}",
            headers={
                "Authorization": f"token {access_token}",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def list_repo_branches(access_token: str, owner: str, repo: str) -> list:
        response = requests.get(
            f"{GITHUB_API_URL}/repos/{owner}/{repo}/branches",
            headers={
                "Authorization": f"token {access_token}",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def download_repository(access_token: str, repo: str, branch: str = "main"):
        response = requests.get(
            f"{GITHUB_API_URL}/repos/{repo}/zipball/{branch}",
            headers={
                "Authorization": f"token {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        response.raise_for_status()
        return response.content

    @staticmethod
    def fetch_tree(access_token: str, owner: str, repo: str, tree_sha: str) -> dict:
        response = requests.get(
            f"{GITHUB_API_URL}/repos/{owner}/{repo}/git/trees/{tree_sha}",
            headers={
                "Authorization": f"token {access_token}",
                "Accept": "application/json",
            },
            params={"recursive": 1},
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def fetch_blob(access_token: str, owner: str, repo: str, blob_sha: str) -> str:
        response = requests.get(
            f"{GITHUB_API_URL}/repos/{owner}/{repo}/git/blobs/{blob_sha}",
            headers={
                "Authorization": f"token {access_token}",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        data = response.json()
        import base64
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
