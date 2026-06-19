from django.test import SimpleTestCase
from requests.exceptions import HTTPError

from embeddings.services.embed import EmbeddingService
from github.services.github_app import GitHubAppService


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
