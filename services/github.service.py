# services/github_service.py
import time
import jwt
import requests
from django.conf import settings
from common.constants import GITHUB_BASE_URL

class GitHubAppService:
    """
    Handles all GitHub App authentication and API calls.
    
    Two-step auth:
    1. App JWT (proves YOU are the GitHub App)
    2. Installation Token (proves you can act on a specific installation)
    """

    def _generate_app_jwt(self):
        """
        GitHub Apps authenticate using a JWT signed with your private key.
        This JWT is short-lived (10 min max).
        """
        now = int(time.time())
        payload = {
            "iat": now - 60,          # issued at (60s ago to account for clock drift)
            "exp": now + (10 * 60),   # expires in 10 minutes
            "iss": settings.GITHUB_APP_ID,
        }
        with open(settings.GITHUB_PRIVATE_KEY_PATH, 'rb') as f:
            private_key = f.read()

        return jwt.encode(payload, private_key, algorithm="RS256")

    def get_installation_access_token(self, installation_id):
        """
        Exchange the App JWT for a short-lived Installation Access Token.
        This token is scoped to the specific repos in that installation.
        Expires in 1 hour — always fetch fresh or cache with expiry.
        """
        app_jwt = self._generate_app_jwt()
        response = requests.post(
            f"{GITHUB_BASE_URL}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
            }
        )
        response.raise_for_status()
        return response.json()["token"]

    def list_repos(self, installation_id):
        """List all repos accessible under this installation."""
        token = self.get_installation_access_token(installation_id)
        response = requests.get(
            f"{GITHUB_BASE_URL}/installation/repositories",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            }
        )
        response.raise_for_status()
        return response.json()["repositories"]

    def get_repo_contents(self, installation_id, repo_full_name, path=""):
        """Read files/directories in a repo."""
        token = self.get_installation_access_token(installation_id)
        response = requests.get(
            f"{GITHUB_BASE_URL}/repos/{repo_full_name}/contents/{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            }
        )
        response.raise_for_status()
        return response.json()