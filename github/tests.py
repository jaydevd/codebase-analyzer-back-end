from django.test import SimpleTestCase
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase
from requests.exceptions import HTTPError
from unittest.mock import patch

from embeddings.services.embed import EmbeddingService
from github.services.github_app import GitHubAppService

User = get_user_model()


class GitHubAppServiceTests(SimpleTestCase):
    def setUp(self):
        self.service = GitHubAppService()

    def test_fetch_tree_returns_recursive_response_when_not_truncated(self):
        recursive_response = {
            "sha": "root-sha",
            "url": "https://api.github.com/root",
            "truncated": False,
            "tree": [{"path": "README.md", "type": "blob", "sha": "blob-1"}],
        }

        self.service.get_installation_token = lambda installation_id: "installation-token"
        self.service._fetch_recursive_tree = lambda owner, repo, tree_sha, token: recursive_response
        self.service._fetch_complete_tree = lambda *args, **kwargs: self.fail("Should not traverse subtrees")

        result = self.service.fetch_tree("owner", "repo", 1, "root-sha")

        self.assertEqual(result, recursive_response)

    def test_fetch_tree_traverses_subtrees_when_recursive_response_is_truncated(self):
        recursive_response = {
            "sha": "root-sha",
            "url": "https://api.github.com/root",
            "truncated": True,
            "tree": [{"path": "partial.txt", "type": "blob", "sha": "partial-blob"}],
        }
        root_non_recursive = {
            "sha": "root-sha",
            "url": "https://api.github.com/root",
            "tree": [
                {"path": "src", "type": "tree", "sha": "src-sha", "url": "https://api.github.com/src"},
                {"path": "README.md", "type": "blob", "sha": "readme-sha", "size": 10},
            ],
        }
        src_tree = {
            "sha": "src-sha",
            "url": "https://api.github.com/src",
            "tree": [
                {"path": "main.py", "type": "blob", "sha": "main-sha", "size": 20},
            ],
        }

        self.service.get_installation_token = lambda installation_id: "installation-token"
        self.service._fetch_recursive_tree = lambda owner, repo, tree_sha, token: recursive_response

        def fake_fetch_tree_by_sha(owner, repo, tree_sha, installation_token):
            if tree_sha == "root-sha":
                return root_non_recursive
            if tree_sha == "src-sha":
                return src_tree
            self.fail(f"Unexpected subtree sha: {tree_sha}")

        self.service._fetch_tree_by_sha = fake_fetch_tree_by_sha

        result = self.service.fetch_tree("owner", "repo", 1, "root-sha")

        self.assertFalse(result["truncated"])
        self.assertEqual(
            result["tree"],
            [
                {"path": "src", "type": "tree", "sha": "src-sha", "url": "https://api.github.com/src"},
                {"path": "README.md", "type": "blob", "sha": "readme-sha", "size": 10},
                {"path": "src/main.py", "type": "blob", "sha": "main-sha", "size": 20},
            ],
        )

    def test_fetch_tree_traverses_nested_subtrees(self):
        root_tree = {
            "sha": "root-sha",
            "url": "https://api.github.com/root",
            "tree": [
                {"path": "src", "type": "tree", "sha": "src-sha"},
            ],
        }
        src_tree = {
            "sha": "src-sha",
            "url": "https://api.github.com/src",
            "tree": [
                {"path": "utils", "type": "tree", "sha": "utils-sha"},
                {"path": "app.py", "type": "blob", "sha": "app-sha"},
            ],
        }
        utils_tree = {
            "sha": "utils-sha",
            "url": "https://api.github.com/utils",
            "tree": [
                {"path": "helpers.py", "type": "blob", "sha": "helpers-sha"},
            ],
        }

        def fake_fetch_tree_by_sha(owner, repo, tree_sha, installation_token):
            mapping = {
                "root-sha": root_tree,
                "src-sha": src_tree,
                "utils-sha": utils_tree,
            }
            return mapping[tree_sha]

        self.service._fetch_tree_by_sha = fake_fetch_tree_by_sha
        result = self.service._fetch_complete_tree(
            "owner",
            "repo",
            {"sha": "root-sha", "url": "https://api.github.com/root", "truncated": True, "tree": []},
            "installation-token",
        )

        self.assertEqual(
            [entry["path"] for entry in result["tree"]],
            ["src", "src/utils", "src/app.py", "src/utils/helpers.py"],
        )

    def test_fetch_tree_preserves_entry_metadata(self):
        self.service._fetch_tree_by_sha = lambda owner, repo, tree_sha, installation_token: {
            "sha": "root-sha",
            "url": "https://api.github.com/root",
            "tree": [
                {
                    "path": "README.md",
                    "mode": "100644",
                    "type": "blob",
                    "sha": "blob-sha",
                    "size": 55,
                    "url": "https://api.github.com/blob",
                }
            ],
        }

        result = self.service._fetch_complete_tree(
            "owner",
            "repo",
            {"sha": "root-sha", "url": "https://api.github.com/root", "truncated": True, "tree": []},
            "installation-token",
        )

        self.assertEqual(
            result["tree"][0],
            {
                "path": "README.md",
                "mode": "100644",
                "type": "blob",
                "sha": "blob-sha",
                "size": 55,
                "url": "https://api.github.com/blob",
            },
        )

    def test_filter_tree_remains_compatible_with_flattened_tree_payload(self):
        tree_response = {
            "tree": [
                {"path": "src", "type": "tree", "sha": "src-sha"},
                {"path": "src/main.py", "type": "blob", "sha": "main-sha", "size": 10},
                {"path": "dist/app.min.js", "type": "blob", "sha": "dist-sha", "size": 10},
            ]
        }

        filtered_files = EmbeddingService().filter_tree(tree_response)

        self.assertEqual(filtered_files, [{"path": "src/main.py", "type": "blob", "sha": "main-sha", "size": 10}])

    def test_fetch_tree_propagates_subtree_fetch_errors(self):
        self.service._fetch_tree_by_sha = lambda owner, repo, tree_sha, installation_token: (_ for _ in ()).throw(
            HTTPError("GitHub subtree fetch failed")
        )

        with self.assertRaisesMessage(HTTPError, "GitHub subtree fetch failed"):
            self.service._fetch_complete_tree(
                "owner",
                "repo",
                {"sha": "root-sha", "url": "https://api.github.com/root", "truncated": True, "tree": []},
                "installation-token",
            )


class GitHubConnectionFlowTests(APITestCase):
    def create_user(self, **overrides):
        payload = {
            "email": "user@example.com",
            "first_name": "Test",
            "last_name": "User",
            "password": "StrongPass123!",
        }
        payload.update(overrides)
        password = payload.pop("password")
        return User.objects.create_user(password=password, **payload)

    def authenticate(self, user=None):
        from rest_framework_simplejwt.tokens import RefreshToken

        user = user or self.create_user()
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        return user

    def test_install_url_can_be_generated_for_authenticated_user(self):
        self.authenticate()

        response = self.client.get("/api/github/install-url/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("url", response.data["data"])

    @patch("github.views.service.get_installation_details")
    def test_installation_callback_links_user_by_state_not_username(self, get_installation_details):
        owner = self.create_user(
            email="owner@example.com",
            github_installation_state="install-state",
        )
        self.create_user(email="other@example.com", github_oauth_username="same-login")
        get_installation_details.return_value = {
            "account": {"login": "same-login"},
        }

        response = self.client.get("/api/github/callback/?state=install-state&installation_id=999")

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn("action=github_repo_connected", response.url)
        owner.refresh_from_db()
        self.assertEqual(owner.github_installation_id, 999)
        self.assertEqual(owner.github_installation_account_login, "same-login")
        self.assertTrue(owner.is_github_installation_active)

    @patch("github.views.service.get_installation_details")
    def test_installation_callback_blocks_mismatched_login_and_installation_accounts(self, get_installation_details):
        owner = self.create_user(
            email="owner@example.com",
            github_installation_state="install-state",
            github_oauth_id=123,
            github_oauth_username="oauth-user",
        )
        get_installation_details.return_value = {
            "account": {"login": "different-install-user"},
        }

        response = self.client.get("/api/github/callback/?state=install-state&installation_id=1000")

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn("error=github_account_mismatch", response.url)
        owner.refresh_from_db()
        self.assertIsNone(owner.github_installation_id)

    def test_repos_endpoint_requires_installation_even_when_oauth_is_present(self):
        user = self.create_user(
            github_oauth_id=123,
            github_oauth_username="oauth-user",
            github_oauth_token="oauth-token",
        )
        self.authenticate(user)

        response = self.client.get("/api/github/repos/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("connect the GitHub App", response.data["message"])

    def test_disconnect_clears_installation_without_unlinking_github_login(self):
        user = self.create_user(
            github_oauth_id=321,
            github_oauth_username="oauth-user",
            github_oauth_token="oauth-token",
            github_installation_id=777,
            github_installation_account_login="oauth-user",
            is_github_installation_active=True,
        )
        self.authenticate(user)

        response = self.client.post("/api/github/disconnect/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertEqual(user.github_oauth_id, 321)
        self.assertIsNone(user.github_installation_id)
        self.assertFalse(user.is_github_installation_active)
