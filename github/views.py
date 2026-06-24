import logging
import re
import secrets

from django.conf import settings
from django.shortcuts import redirect, get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from requests.exceptions import RequestException

from auth.models import User
from common.responses import error_response, success_response
from github.models import GithubRepos, RepoBranch, BranchScan
from github.serializers import (
    GitHubCallbackQuerySerializer,
    DownloadRepoSerializer,
    BranchListSerializer,
    ScanReportBranchSerializer,
    PreviousScanSerializer,
)
from github.services.github_app import GitHubAppService

logger = logging.getLogger(__name__)
service = GitHubAppService()


class GitHubInstallUrlView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not settings.GITHUB_APP_SLUG:
            return error_response(
                "GitHub App slug is not configured.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        state = secrets.token_urlsafe(32)

        User.objects.filter(id=request.user.id).update(github_installation_state=state)
        install_url = (
            f"https://github.com/apps/{settings.GITHUB_APP_SLUG}/installations/new?state={state}"
        )
        return success_response("GitHub installation URL generated.", data={"url": install_url})


class GitHubCallbackView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        serializer = GitHubCallbackQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        state = serializer.validated_data["state"]
        installation_id = serializer.validated_data["installation_id"]

        try:
            installation_details = service.get_installation_details(installation_id)
        except RequestException:
            logger.exception("Failed to fetch GitHub installation details for %s", installation_id)
            return error_response(
                "Unable to fetch GitHub installation details.",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

        github_username = installation_details.get("account", {}).get("login", "")

        User.objects.filter(github_installation_state=state).update(
            github_username=github_username,
            github_installation_id=installation_id,
        )

        return success_response(message="Installation successful. Webhook will sync repos.")


class ListReposView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        if not user.is_github_installation_active or not user.github_installation_id:
            return error_response(
                "GitHub installation is incomplete.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        try:
            repos = service.get_installation_repositories(user.github_installation_id)
        except RequestException:
            logger.exception(
                "Failed to fetch GitHub repos for installation %s",
                user.github_installation_id,
            )
            return error_response(
                "Unable to retrieve GitHub repositories.",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

        for repo_data in repos:
            repo_obj, _ = GithubRepos.objects.update_or_create(
                repo_id=repo_data["id"],
                defaults={
                    "user_id": user,
                    "name": repo_data["name"],
                    "full_name": repo_data["full_name"],
                    "private": repo_data.get("private", False),
                    "default_branch": repo_data.get("default_branch", "main"),
                    "is_deleted": False,
                    "is_active": True,
                },
            )

        db_repos = GithubRepos.objects.filter(user_id=user, is_deleted=False)
        data = [
            {
                "id": r.repo_id,
                "name": r.name,
                "full_name": r.full_name,
                "private": r.private,
                "default_branch": r.default_branch,
                "status": r.status,
            }
            for r in db_repos
        ]
        return success_response("GitHub repositories fetched successfully.", data=data)


class GitHubWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        signature = request.headers.get("X-Hub-Signature-256", "")
        raw_body = request.body
        secret = settings.GITHUB_WEBHOOK_SECRET

        if not service.verify_webhook_signature(raw_body, signature, secret):
            logger.warning("Invalid GitHub webhook signature.")
            return error_response(
                "Invalid webhook signature.",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        event = request.headers.get("X-GitHub-Event", "")

        payload = request.data

        logger.info(
            "GitHub webhook received event=%s installation_id=%s action=%s",
            event,
            payload.get("installation", {}).get("id"),
            payload.get("action"),
        )

        handler_name = f"handle_{event.replace('-', '_')}"
        handler = getattr(self, handler_name, self.handle_default)

        return handler(payload)

    def _sync_branches(self, repo_obj, installation_id):
        try:
            owner, repo_name = repo_obj.full_name.split("/", 1)
            branches = service.list_repo_branches(owner, repo_name, installation_id)
        except Exception:
            logger.exception("Failed to sync branches for %s", repo_obj.full_name)
            return

        for branch_data in branches:
            commit_sha = branch_data.get("commit", {}).get("sha", "")
            commit_url = (
                f"https://github.com/{repo_obj.full_name}/commit/{commit_sha}"
                if commit_sha
                else ""
            )
            RepoBranch.objects.update_or_create(
                repo=repo_obj,
                name=branch_data["name"],
                defaults={
                    "commit_sha": commit_sha,
                    "commit_url": commit_url,
                    "is_active": True,
                },
            )

    def handle_installation(self, payload):
        installation = payload.get("installation", {})
        action = payload.get("action")
        installation_id = installation.get("id")

        if action == "created":
            token = service.get_installation_token(installation_id)

            User.objects.filter(github_installation_id=installation_id).update(
                github_installation_access_token=token,
                is_github_installation_active=True,
            )

            repos = service.get_installation_repositories(installation_id)
            for repo_data in repos:
                repo_obj, _ = GithubRepos.objects.update_or_create(
                    repo_id=repo_data["id"],
                    defaults={
                        "user_id": User.objects.get(github_installation_id=installation_id),
                        "name": repo_data["name"],
                        "full_name": repo_data["full_name"],
                        "private": repo_data.get("private", False),
                        "default_branch": repo_data.get("default_branch", "main"),
                        "is_deleted": False,
                        "is_active": True,
                    },
                )
                self._sync_branches(repo_obj, installation_id)

        elif action == "deleted" and installation_id:
            GithubRepos.objects.filter(
                user_id__github_installation_id=installation_id
            ).update(is_deleted=True, is_active=False)
            RepoBranch.objects.filter(
                repo__user_id__github_installation_id=installation_id
            ).update(is_active=False)
            User.objects.filter(github_installation_id=installation_id).update(
                github_installation_access_token=None,
                github_installation_state=None,
                is_github_installation_active=False,
            )

        return success_response("GitHub installation event processed.")

    def handle_installation_repositories(self, payload):
        action = payload.get("action")
        installation_id = payload.get("installation", {}).get("id")

        try:
            user = User.objects.get(github_installation_id=installation_id)
        except User.DoesNotExist:
            return success_response("User not found; event skipped.")

        if action == "added":
            for repo_data in payload.get("repositories_added", []):
                repo_obj, _ = GithubRepos.objects.update_or_create(
                    repo_id=repo_data["id"],
                    defaults={
                        "user_id": user,
                        "name": repo_data["name"],
                        "full_name": repo_data["full_name"],
                        "private": repo_data.get("private", False),
                        "is_deleted": False,
                        "is_active": True,
                    },
                )
                self._sync_branches(repo_obj, installation_id)

        elif action == "removed":
            repo_ids = [r["id"] for r in payload.get("repositories_removed", [])]
            GithubRepos.objects.filter(repo_id__in=repo_ids).update(
                is_deleted=True, is_active=False
            )
            RepoBranch.objects.filter(repo__repo_id__in=repo_ids).update(is_active=False)

        return success_response("GitHub installation_repositories event processed.")

    def handle_push(self, payload):
        repository = payload.get("repository", {}).get("full_name")
        ref = payload.get("ref")
        logger.info("Received push event for %s on ref %s", repository, ref)
        return success_response("GitHub push event processed.")

    def handle_default(self, payload):
        return success_response("GitHub webhook received.")


class DownloadRepo(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DownloadRepoSerializer

    def post(self, request):
        user = request.user

        if not user.is_github_installation_active or not user.github_installation_id:
            return error_response(
                "GitHub installation has not been completed for the current user.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        try:
            serializer = self.serializer_class(data=request.data)
            if not serializer.is_valid():
                return error_response(
                    "Invalid request data.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            branch = serializer.validated_data.get("branch")
            repo_full_name = serializer.validated_data.get("repo_full_name")

            service.download_repository(repo_full_name, user.github_installation_id, branch)

        except RequestException:
            logger.exception(
                "Failed to download repo for installation %s",
                user.github_installation_id,
            )
            return error_response(
                "Unable to download github repo.",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

        return success_response("GitHub repo downloaded successfully.")


class ListRepoBranchesView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = [BranchListSerializer]

    def get(self, request, repo):
        user = request.user
        owner = user.github_username
        installation_id = user.github_installation_id

        branches = service.list_repo_branches(owner, repo, installation_id)

        return success_response(message="branches listed successfully", data=branches)


class SearchReposView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        query = request.query_params.get("query", "")

        repos = GithubRepos.objects.filter(user_id=user, is_deleted=False)
        if query:
            repos = repos.filter(name__icontains=query)

        data = [
            {
                "id": r.repo_id,
                "name": r.name,
                "full_name": r.full_name,
                "private": r.private,
                "default_branch": r.default_branch,
                "status": r.status,
            }
            for r in repos
        ]
        return success_response(message="Repos found", data=data)


class RepoScanReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, repo_id):
        repo = get_object_or_404(
            GithubRepos, repo_id=repo_id, user_id=request.user, is_deleted=False
        )

        branches = RepoBranch.objects.filter(repo=repo, is_active=True)

        data = []
        for branch in branches:
            scans = branch.scans.all().order_by("-started_at")
            previous_scans = [
                {
                    "commit_url": s.commit_url,
                    "commit_sha": s.commit_sha,
                    "indexed_at": s.completed_at or s.started_at,
                }
                for s in scans
            ]
            data.append(
                {
                    "branch": branch.name,
                    "status": branch.status,
                    "last_indexed_at": branch.last_indexed_at,
                    "previous_scans": previous_scans,
                }
            )

        return success_response(
            f"Scan report fetched successfully {repo.full_name}",
            data=data,
        )
