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
import base64

_blob_cache: dict[str, str] = {}

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
                "User-Agent": settings.GITHUB_APP_SLUG,
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
                "User-Agent": settings.GITHUB_APP_SLUG,
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
                "User-Agent": settings.GITHUB_APP_SLUG,
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
    
    def download_repository(self, repo: str, installation_id: int, branch: str = "main") -> None:
        installation_token = self.get_installation_token(installation_id)
        response = requests.get(
            f"{GITHUB_BASE_URL}/repos/{repo}/zipball/{branch}",
            headers={
                "Authorization": f"token {installation_token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": settings.GITHUB_APP_SLUG,
            },
        )
        response.raise_for_status()
        
        # Here you would implement the logic to clone the repository using the clone_url and branch.
        # This is a placeholder for the actual cloning logic, which might involve using GitPython or subprocess to call git.
        # For example:
        # git.Repo.clone_from(clone_url, local_path, branch=branch)

    def listRepoBranches(self, repo:str, installation_id):
        installation_token = self.get_installation_token(installation_id)
        response = requests.get(
            f"{GITHUB_BASE_URL}/repos/{repo}/branches",
            headers={
                "Authorization": f"token {installation_token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": settings.GITHUB_APP_SLUG,
            }
        )
        print("listRepoBranches response: ", response.json())

        response.raise_for_status()
        return response.json()

    def getRepo(self, repo: str, installation_id: int):
        installation_token = self.get_installation_token(installation_id)
        response = requests.get(
            f"{GITHUB_BASE_URL}/repos/{repo}",
            headers={
                "Authorization": f"token {installation_token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": settings.GITHUB_APP_SLUG,
            }
        )
        print("getRepo response: ", response.json())

        response.raise_for_status()
        return response.json()
    
    def getRepoFilesForBranch(self, repo: str, sha: str, installation_id: int):
        installation_token = self.get_installation_token(installation_id)
        config = {
            "url": f"{GITHUB_BASE_URL}/repos/{repo}/git/trees/{sha}?recursive=1",
            "headers": {
                "Authorization": f"token {installation_token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": settings.GITHUB_APP_SLUG,
            }
        }
        response = requests.get(config["url"],config["headers"])

        print("file-tree response", response.json())

        return response.json()

    def getRepoBranch(self, repo: str, branch_ref: str, installation_id: int):
        installation_token = self.get_installation_token(installation_id)
        response = requests.get(
            f"{GITHUB_BASE_URL}/repos/{repo}/git/ref/heads/{branch_ref}",
            headers={
                "Authorization": f"token {installation_token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": settings.GITHUB_APP_SLUG,
            }
        )
        print("getRepoBranch response: ", response.json())

        response.raise_for_status()
        return response.json()

    def fetch_tree(self, owner: str, repo: str, installation_id: int, commit_sha:str = None):
        
        installation_token = self.get_installation_token(installation_id)

        # if branch == None or branch == "":
        #     repository = self.getRepo(repo, installation_id)
        #     branch_ref = repository.get("default_branch")
        #     branch = self.getRepoBranch(repo, branch_ref, installation_id)
        #     sha = branch.get("object").get("sha")
        # else:
        #     sha = branch.get("commit").get("sha")

        response = requests.get(
            f"{GITHUB_BASE_URL}/repos/{owner}/{repo}/git/trees/{commit_sha}?recursive=1",
            headers={
                "Authorization": f"token {installation_token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": settings.GITHUB_APP_SLUG,
            }
        )
        print("fetch_tree response: ", response.json())
        
        response.raise_for_status()
        return response.json()
    
    def fetch_blob(self, installation_id: int, owner: str, repo: str, blob_sha: str) -> str:
        if blob_sha in _blob_cache:
            return _blob_cache[blob_sha]
        
        installation_token = self.get_installation_token(installation_id)
        response = requests.get(
            f'{GITHUB_BASE_URL}/repos/{owner}/{repo}/git/blobs/{blob_sha}',
            headers={
                "Authorization": f"token {installation_token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": settings.GITHUB_APP_SLUG,
            }
        )
        response.raise_for_status()

        data = response.json()
        content = base64.b64decode(data['content']).decode('utf-8', errors='replace')
        _blob_cache[blob_sha] = content
        return content


    def fetch_all_blobs(self, installation_id: int, owner: str, repo: str, filtered_files: list[dict]) -> dict[str, str]:
        """Returns { file_path: content }"""
        results = {}
        for entry in filtered_files:
            try:
                content = self.fetch_blob(installation_id, owner, repo, entry['sha'])
                results[entry['path']] = content
            except Exception as e:
                print(f"Skipping {entry['path']}: {e}")
        return results