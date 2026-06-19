import hashlib
import hmac
import time
from collections import deque
from copy import deepcopy
from pathlib import Path
from typing import Any

import jwt
import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

import base64

GITHUB_BASE_URL = "https://api.github.com"

_blob_cache: dict[str, str] = {}

class GitHubAppService:
    """GitHub App authentication and installation helper."""

    def _build_installation_headers(self, installation_token: str) -> dict[str, str]:
        return {
            "Authorization": f"token {installation_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": settings.GITHUB_APP_SLUG,
        }

    def _github_get(self, url: str, installation_token: str, *, params: dict[str, Any] | None = None):
        response = requests.get(
            url,
            headers=self._build_installation_headers(installation_token),
            params=params,
        )
        response.raise_for_status()
        return response.json()

    def _fetch_recursive_tree(
        self,
        owner: str,
        repo: str,
        tree_sha: str,
        installation_token: str,
    ) -> dict[str, Any]:
        return self._github_get(
            f"{GITHUB_BASE_URL}/repos/{owner}/{repo}/git/trees/{tree_sha}",
            installation_token,
            params={"recursive": 1},
        )

    def _fetch_tree_by_sha(
        self,
        owner: str,
        repo: str,
        tree_sha: str,
        installation_token: str,
    ) -> dict[str, Any]:
        return self._github_get(
            f"{GITHUB_BASE_URL}/repos/{owner}/{repo}/git/trees/{tree_sha}",
            installation_token,
        )

    @staticmethod
    def _join_tree_path(parent_path: str, child_path: str) -> str:
        if not parent_path:
            return child_path
        return f"{parent_path.rstrip('/')}/{child_path.lstrip('/')}"

    def _fetch_complete_tree(
        self,
        owner: str,
        repo: str,
        root_tree: dict[str, Any],
        installation_token: str,
    ) -> dict[str, Any]:
        root_sha = root_tree["sha"]
        root_non_recursive = self._fetch_tree_by_sha(owner, repo, root_sha, installation_token)
        aggregated_tree: list[dict[str, Any]] = []
        queue: deque[tuple[str, list[dict[str, Any]]]] = deque(
            [("", root_non_recursive.get("tree", []))]
        )

        while queue:
            parent_path, entries = queue.popleft()
            for entry in entries:
                full_path = self._join_tree_path(parent_path, entry["path"])
                normalized_entry = deepcopy(entry)
                normalized_entry["path"] = full_path
                aggregated_tree.append(normalized_entry)

                if entry.get("type") == "tree":
                    subtree = self._fetch_tree_by_sha(
                        owner,
                        repo,
                        entry["sha"],
                        installation_token,
                    )
                    queue.append((full_path, subtree.get("tree", [])))

        final_tree = deepcopy(root_tree)
        final_tree["tree"] = aggregated_tree
        final_tree["truncated"] = False
        return final_tree

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
            headers=self._build_installation_headers(installation_token),
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
            headers=self._build_installation_headers(installation_token),
        )
        response.raise_for_status()
        
        # Here you would implement the logic to clone the repository using the clone_url and branch.
        # This is a placeholder for the actual cloning logic, which might involve using GitPython or subprocess to call git.
        # For example:
        # git.Repo.clone_from(clone_url, local_path, branch=branch)

    def list_repo_branches(self, owner:str, repo:str, installation_id:int):
        installation_token = self.get_installation_token(installation_id)
        response = requests.get(
            f"{GITHUB_BASE_URL}/repos/{owner}/{repo}/branches",
            headers=self._build_installation_headers(installation_token),
        )

        response.raise_for_status()
        return response.json()

    def get_repo(self, repo: str, installation_id: int):
        installation_token = self.get_installation_token(installation_id)
        response = requests.get(
            f"{GITHUB_BASE_URL}/repos/{repo}",
            headers=self._build_installation_headers(installation_token),
        )

        response.raise_for_status()
        return response.json()
    
    # def getRepoFilesForBranch(self, repo: str, sha: str, installation_id: int):
    #     installation_token = self.get_installation_token(installation_id)
    #     config = {
    #         "url": f"{GITHUB_BASE_URL}/repos/{repo}/git/trees/{sha}?recursive=1",
    #         "headers": {
    #             "Authorization": f"token {installation_token}",
    #             "Accept": "application/vnd.github+json",
    #             "User-Agent": settings.GITHUB_APP_SLUG,
    #         }
    #     }
    #     response = requests.get(config["url"],config["headers"])

    #     print("file-tree response", response.json())

    #     return response.json()

    def get_repo_branch(self, repo: str, branch_ref: str, installation_id: int):
        installation_token = self.get_installation_token(installation_id)
        response = requests.get(
            f"{GITHUB_BASE_URL}/repos/{repo}/git/ref/heads/{branch_ref}",
            headers=self._build_installation_headers(installation_token),
        )

        response.raise_for_status()
        return response.json()

    def fetch_tree(self, owner: str, repo: str, installation_id: int, commit_sha:str = None):
        installation_token = self.get_installation_token(installation_id)
        root_tree = self._fetch_recursive_tree(owner, repo, commit_sha, installation_token)
        if not root_tree.get("truncated"):
            return root_tree
        return self._fetch_complete_tree(owner, repo, root_tree, installation_token)
    
    def fetch_blob(self, installation_id: int, owner: str, repo: str, blob_sha: str) -> str:
        if blob_sha in _blob_cache:
            return _blob_cache[blob_sha]
        
        installation_token = self.get_installation_token(installation_id)
        response = requests.get(
            f'{GITHUB_BASE_URL}/repos/{owner}/{repo}/git/blobs/{blob_sha}',
            headers=self._build_installation_headers(installation_token),
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


github_service = GitHubAppService()
