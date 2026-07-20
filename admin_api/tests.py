from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import ChatSession
from github.models import BranchScan, BranchScanStatus, GithubRepos, RepoBranch, ScanError

User = get_user_model()


class AdminAPITestCase(APITestCase):
    stats_url = "/admin/stats/"
    scans_over_time_url = "/admin/stats/scans-over-time/"
    users_url = "/admin/users/"
    scans_url = "/admin/scans/"
    repos_url = "/admin/repos/"
    logs_url = "/admin/logs/"

    def create_admin(self, **overrides):
        payload = {
            "email": "admin@example.com",
            "first_name": "Admin",
            "last_name": "User",
            "password": "AdminPass123!",
            "role": "admin",
        }
        payload.update(overrides)
        password = payload.pop("password")
        return User.objects.create_user(password=password, **payload)

    def create_user(self, **overrides):
        payload = {
            "email": "user@example.com",
            "first_name": "Regular",
            "last_name": "User",
            "password": "UserPass123!",
        }
        payload.update(overrides)
        password = payload.pop("password")
        return User.objects.create_user(password=password, **payload)

    def create_repo(self, user, **overrides):
        payload = {
            "repo_id": 12345,
            "name": "test-repo",
            "full_name": "owner/test-repo",
            "user_id": user,
        }
        payload.update(overrides)
        return GithubRepos.objects.create(**payload)

    def create_branch_scan(self, repo_branch, status_override=BranchScanStatus.SCANNED, **overrides):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        payload = {
            "commit_sha": "abc123",
            "commit_url": "https://github.com/owner/repo/commit/abc123",
            "status": status_override,
            "started_at": now_ts - 100,
            "completed_at": now_ts,
        }
        payload.update(overrides)
        return BranchScan.objects.create(repo_branch=repo_branch, **payload)

    def authenticate(self, user=None):
        if user is None:
            user = self.create_admin()
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        return user, refresh

    # --- Auth tests ---

    def test_admin_endpoints_require_authentication(self):
        urls = [self.stats_url, self.users_url, self.scans_url, self.repos_url, self.logs_url]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED, f"{url} should 401")

    def test_admin_endpoints_reject_regular_user(self):
        regular = self.create_user(email="regular@example.com")
        refresh = RefreshToken.for_user(regular)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        urls = [self.stats_url, self.users_url, self.scans_url, self.repos_url, self.logs_url]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, f"{url} should 403")

    # --- Stats tests ---

    def test_stats_endpoint(self):
        self.authenticate()
        now = datetime.now(timezone.utc)
        now_ts = int(now.timestamp())
        thirty_days_ago_ts = int(now.timestamp()) - 30 * 86400

        # Create some test data
        user = self.create_user(email="stats-user@example.com")

        # Create a chat session for the user
        ChatSession.objects.create(user_id=user)

        # Create a repo
        repo = self.create_repo(user=user)
        branch = RepoBranch.objects.create(repo=repo, name="main", commit_sha="abc")

        # Create a completed scan
        BranchScan.objects.create(
            repo_branch=branch,
            commit_sha="abc",
            commit_url="https://github.com/owner/repo/commit/abc",
            status=BranchScanStatus.SCANNED,
            started_at=now_ts - 500,
            completed_at=now_ts,
        )

        # Create a failed scan (within 30 days)
        BranchScan.objects.create(
            repo_branch=branch,
            commit_sha="def",
            commit_url="https://github.com/owner/repo/commit/def",
            status=BranchScanStatus.FAILED,
            started_at=thirty_days_ago_ts + 100,
            completed_at=thirty_days_ago_ts + 200,
        )

        response = self.client.get(self.stats_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertIsInstance(data["total_users"], int)
        self.assertIsInstance(data["active_users"], int)
        self.assertIsInstance(data["total_repos"], int)
        self.assertIsInstance(data["scanned_repos"], int)
        self.assertIsInstance(data["total_chats"], int)
        self.assertIsInstance(data["scans_today"], int)
        self.assertIsInstance(data["failed_scans"], int)
        self.assertTrue(data["avg_scan_duration_seconds"] is None or isinstance(data["avg_scan_duration_seconds"], int))

    def test_scans_over_time_endpoint(self):
        self.authenticate()

        # Create a repo + branch
        user = self.create_user()
        repo = self.create_repo(user=user)
        branch = RepoBranch.objects.create(repo=repo, name="main", commit_sha="abc")

        # Create a scan within last 30 days
        now = datetime.now(timezone.utc)
        three_days_ago_ts = int(now.timestamp()) - 3 * 86400
        BranchScan.objects.create(
            repo_branch=branch,
            commit_sha="abc",
            commit_url="https://github.com/owner/repo/commit/abc",
            status=BranchScanStatus.SCANNED,
            started_at=three_days_ago_ts,
        )

        response = self.client.get(self.scans_over_time_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["data"]
        self.assertEqual(len(results), 30)
        self.assertIn("date", results[0])
        self.assertIn("completed", results[0])
        self.assertIn("failed", results[0])
        self.assertIn("total", results[0])

    # --- User management tests ---

    def test_user_list_paginated(self):
        self.authenticate()
        # Create a few users
        for i in range(5):
            self.create_user(email=f"user{i}@example.com")

        response = self.client.get(self.users_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("count", response.data["data"])
        self.assertIn("results", response.data["data"])
        self.assertGreaterEqual(len(response.data["data"]["results"]), 5)

    def test_user_list_search(self):
        self.authenticate()
        self.create_user(email="alice@example.com", first_name="Alice")
        self.create_user(email="bob@example.com", first_name="Bob")

        response = self.client.get(f"{self.users_url}?search=alice")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["data"]["results"]
        self.assertTrue(all("alice" in u["email"].lower() or "alice" in u["first_name"].lower() for u in results))

    def test_user_list_filter_by_role(self):
        self.authenticate()
        self.create_user(email="regular@example.com", role="user")

        response = self.client.get(f"{self.users_url}?role=user")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["data"]["results"]
        if results:
            self.assertTrue(all(u["role"] == "user" for u in results))

    def test_user_list_filter_by_is_suspended(self):
        admin_user = self.authenticate()[0]
        self.create_user(email="suspended@example.com", is_active=False)
        self.create_user(email="active@example.com", is_active=True)

        response = self.client.get(f"{self.users_url}?is_suspended=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["data"]["results"]
        for u in results:
            self.assertTrue(u["is_suspended"])

    def test_user_detail(self):
        admin_user = self.authenticate()[0]
        response = self.client.get(f"{self.users_url}{admin_user.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["email"], admin_user.email)

    def test_user_update(self):
        user = self.create_user(email="updatable@example.com", first_name="Old")
        self.authenticate()

        response = self.client.patch(
            f"{self.users_url}{user.pk}/",
            {"first_name": "Updated", "role": "admin"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertEqual(user.first_name, "Updated")
        self.assertEqual(user.role, "admin")

    def test_user_delete_hard(self):
        user = self.create_user(email="deletable@example.com")
        self.authenticate()

        response = self.client.delete(f"{self.users_url}{user.pk}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())

    def test_user_suspend(self):
        user = self.create_user(email="suspendable@example.com")
        self.authenticate()

        response = self.client.post(f"{self.users_url}{user.pk}/suspend/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_user_activate(self):
        user = self.create_user(email="activatable@example.com", is_active=False)
        self.authenticate()

        response = self.client.post(f"{self.users_url}{user.pk}/activate/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertTrue(user.is_active)

    # --- Scan management tests ---

    def test_scan_list(self):
        self.authenticate()
        user = self.create_user()
        repo = self.create_repo(user=user)
        branch = RepoBranch.objects.create(repo=repo, name="main", commit_sha="abc")
        self.create_branch_scan(repo_branch=branch)

        response = self.client.get(self.scans_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data["data"])

    def test_scan_detail(self):
        self.authenticate()
        user = self.create_user()
        repo = self.create_repo(user=user)
        branch = RepoBranch.objects.create(repo=repo, name="main", commit_sha="abc")
        scan = self.create_branch_scan(repo_branch=branch)

        response = self.client.get(f"{self.scans_url}{scan.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["id"], str(scan.pk))

    def test_scan_retry(self):
        self.authenticate()
        user = self.create_user()
        repo = self.create_repo(user=user)
        branch = RepoBranch.objects.create(repo=repo, name="main", commit_sha="abc")
        scan = self.create_branch_scan(
            repo_branch=branch,
            status_override=BranchScanStatus.FAILED,
        )

        response = self.client.post(f"{self.scans_url}{scan.pk}/retry/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(branch.scans.count(), 2)

    def test_scan_list_filter_by_status(self):
        self.authenticate()
        user = self.create_user()
        repo = self.create_repo(user=user)
        branch = RepoBranch.objects.create(repo=repo, name="main", commit_sha="abc")
        self.create_branch_scan(repo_branch=branch, status_override=BranchScanStatus.SCANNED)
        self.create_branch_scan(
            repo_branch=branch,
            status_override=BranchScanStatus.FAILED,
            commit_sha="def",
            commit_url="https://github.com/owner/repo/commit/def",
        )

        response = self.client.get(f"{self.scans_url}?status=completed")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["data"]["results"]
        self.assertTrue(all(r["status"] == "completed" for r in results))

    # --- Repo management tests ---

    def test_repo_list(self):
        self.authenticate()
        user = self.create_user()
        repo = self.create_repo(user=user)
        RepoBranch.objects.create(repo=repo, name="main", commit_sha="abc")
        RepoBranch.objects.create(repo=repo, name="dev", commit_sha="def")

        response = self.client.get(self.repos_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data["data"])
        # Check branch_count annotation
        if response.data["data"]["results"]:
            self.assertIn("branch_count", response.data["data"]["results"][0])

    def test_repo_list_filter_by_owner(self):
        admin = self.authenticate()[0]
        user1 = self.create_user(email="owner1@example.com")
        user2 = self.create_user(email="owner2@example.com")
        self.create_repo(user=user1, repo_id=111, name="repo-a")
        self.create_repo(user=user2, repo_id=222, name="repo-b")

        response = self.client.get(f"{self.repos_url}?owner_id={user1.pk}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["data"]["results"]
        for r in results:
            self.assertEqual(r["owner_id"], str(user1.pk))

    def test_repo_delete(self):
        self.authenticate()
        user = self.create_user()
        repo = self.create_repo(user=user)

        response = self.client.delete(f"{self.repos_url}{repo.pk}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(GithubRepos.objects.filter(pk=repo.pk).exists())

    def test_repo_rescan(self):
        self.authenticate()
        user = self.create_user()
        repo = self.create_repo(user=user)
        RepoBranch.objects.create(repo=repo, name=repo.default_branch, commit_sha="abc")

        response = self.client.post(f"{self.repos_url}{repo.pk}/rescan/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(repo.branches.get(name=repo.default_branch).scans.count(), 1)

    # --- Log tests ---

    def test_log_list(self):
        self.authenticate()
        user = self.create_user()
        repo = self.create_repo(user=user)
        branch = RepoBranch.objects.create(repo=repo, name="main", commit_sha="abc")
        scan = self.create_branch_scan(repo_branch=branch)
        ScanError.objects.create(
            branch_scan=scan,
            error_message="Something went wrong",
            error_type="CloningError",
        )

        response = self.client.get(self.logs_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data["data"])

    def test_log_list_search(self):
        self.authenticate()
        user = self.create_user()
        repo = self.create_repo(user=user, full_name="owner/my-repo")
        branch = RepoBranch.objects.create(repo=repo, name="main", commit_sha="abc")
        scan = self.create_branch_scan(repo_branch=branch)
        ScanError.objects.create(
            branch_scan=scan,
            error_message="Failed to clone my-repo",
            error_type="CloningError",
        )

        response = self.client.get(f"{self.logs_url}?search=clone")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["data"]["results"]
        self.assertGreaterEqual(len(results), 1)
