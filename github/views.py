import logging
import re
import secrets

from django.conf import settings
from django.shortcuts import redirect, get_object_or_404
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from requests.exceptions import RequestException

from auth.models import User
from common.responses import error_response, success_response
from common.swagger import (
    build_success_envelope_serializer,
    build_error_envelope_serializer,
)
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


@extend_schema(
    tags=["GitHub"],
    responses={
        200: build_success_envelope_serializer(
            "GitHubInstallUrlResponse",
            inline_serializer("InstallUrlData", fields={"url": serializers.URLField()}),
        ),
        500: build_error_envelope_serializer("GitHubInstallUrlError"),
    },
)
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


@extend_schema(
    tags=["GitHub"],
    parameters=[
        OpenApiParameter(name="state", type=str, location=OpenApiParameter.QUERY, required=True, description="Installation state token"),
        OpenApiParameter(name="installation_id", type=int, location=OpenApiParameter.QUERY, required=True, description="GitHub App installation ID"),
        OpenApiParameter(name="setup_action", type=str, location=OpenApiParameter.QUERY, required=False, description="Setup action from GitHub"),
    ],
    responses={
        302: OpenApiResponse(description="Redirect to frontend with success/error"),
    },
)
class GitHubCallbackView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        serializer = GitHubCallbackQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        state = serializer.validated_data["state"]
        installation_id = serializer.validated_data["installation_id"]
        user = User.objects.filter(github_installation_state=state).first()
        if not user:
            return redirect(self._frontend_url(error="invalid_installation_state"))

        try:
            installation_details = service.get_installation_details(installation_id)
        except RequestException:
            logger.exception("Failed to fetch GitHub installation details for %s", installation_id)
            return redirect(self._frontend_url(error="installation_lookup_failed"))

        github_account_login = installation_details.get("account", {}).get("login", "")
        existing_owner = User.objects.filter(github_installation_id=installation_id).exclude(pk=user.pk).first()
        if existing_owner:
            return redirect(self._frontend_url(error="github_repo_installation_in_use"))
        if user.github_installation_id and user.github_installation_id != installation_id:
            return redirect(self._frontend_url(error="disconnect_existing_github_installation"))
        if user.github_oauth_username and github_account_login and user.github_oauth_username != github_account_login:
            return redirect(self._frontend_url(error="github_account_mismatch"))

        User.objects.filter(pk=user.pk).update(
            github_installation_account_login=github_account_login,
            github_installation_id=installation_id,
            github_installation_state=None,
            is_github_installation_active=True,
            github_username=github_account_login or user.github_oauth_username or user.github_username,
        )

        return redirect(self._frontend_url(action="github_repo_connected"))

    @staticmethod
    def _frontend_url(error=None, action=None):
        query_parts = []
        if error:
            query_parts.append(f"error={error}")
        if action:
            query_parts.append(f"action={action}")
        suffix = f"?{'&'.join(query_parts)}" if query_parts else ""
        return f"{settings.FRONTEND_URL}/auth/callback{suffix}"


_repo_item_serializer = inline_serializer(
    "RepoItem",
    fields={
        "id": serializers.IntegerField(),
        "name": serializers.CharField(),
        "full_name": serializers.CharField(),
        "url": serializers.URLField(),
        "private": serializers.BooleanField(),
        "default_branch": serializers.CharField(),
        "status": serializers.CharField(),
    },
)

@extend_schema(
    tags=["GitHub"],
    responses={
        200: build_success_envelope_serializer("ListReposResponse", _repo_item_serializer),
        404: build_error_envelope_serializer("ListReposNotFound"),
        502: build_error_envelope_serializer("ListReposBadGateway"),
    },
)
class ListReposView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        try:
            if user.is_github_installation_active and user.github_installation_id:
                repos = service.get_installation_repositories(user.github_installation_id)
            else:
                return error_response(
                    "No GitHub repository connection found. Please connect the GitHub App.",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
        except RequestException:
            logger.exception("Failed to fetch GitHub repos for user %s", user.id)
            return error_response(
                "Unable to retrieve GitHub repositories.",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

        for repo_data in repos:
            GithubRepos.objects.update_or_create(
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
                "url": f"https://github.com/{r.full_name}",
                "private": r.private,
                "default_branch": r.default_branch,
                "status": r.status,
            }
            for r in db_repos
        ]
        return success_response("GitHub repositories fetched successfully.", data=data)


@extend_schema(
    tags=["GitHub"],
    request=inline_serializer("WebhookPayload", fields={}),
    parameters=[
        OpenApiParameter(name="X-Hub-Signature-256", type=str, location=OpenApiParameter.HEADER, required=True, description="HMAC-SHA256 webhook signature"),
        OpenApiParameter(name="X-GitHub-Event", type=str, location=OpenApiParameter.HEADER, required=True, description="GitHub webhook event type"),
    ],
    responses={
        200: build_success_envelope_serializer("WebhookResponse"),
        401: build_error_envelope_serializer("WebhookAuthError"),
    },
)
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
            owner = User.objects.get(github_installation_id=installation_id)
            for repo_data in repos:
                repo_obj, _ = GithubRepos.objects.update_or_create(
                    repo_id=repo_data["id"],
                    defaults={
                        "user_id": owner,
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
                github_installation_account_login=None,
                github_installation_state=None,
                is_github_installation_active=False,
                github_username=None,
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


@extend_schema(
    tags=["GitHub"],
    request=DownloadRepoSerializer,
    responses={
        200: build_success_envelope_serializer("DownloadRepoResponse"),
        400: build_error_envelope_serializer("DownloadRepoError"),
        404: build_error_envelope_serializer("DownloadRepoNotFound"),
        502: build_error_envelope_serializer("DownloadRepoBadGateway"),
    },
)
class DownloadRepo(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DownloadRepoSerializer

    def post(self, request):
        user = request.user

        try:
            serializer = self.serializer_class(data=request.data)
            if not serializer.is_valid():
                return error_response(
                    "Invalid request data.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            branch = serializer.validated_data.get("branch", "main")
            repo_full_name = serializer.validated_data.get("repo_full_name")

            if user.is_github_installation_active and user.github_installation_id:
                service.download_repository(repo_full_name, user.github_installation_id, branch)
            else:
                return error_response(
                    "No GitHub repository connection found. Please connect the GitHub App.",
                    status_code=status.HTTP_404_NOT_FOUND,
                )

        except RequestException:
            logger.exception("Failed to download repo %s", repo_full_name)
            return error_response(
                "Unable to download GitHub repo.",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

        return success_response("GitHub repo downloaded successfully.")


@extend_schema(
    tags=["GitHub"],
    parameters=[
        OpenApiParameter(name="repo", type=str, location=OpenApiParameter.PATH, required=True, description="Repository name (case-insensitive)"),
    ],
    responses={
        200: build_success_envelope_serializer("ListBranchesResponse"),
        404: build_error_envelope_serializer("ListBranchesNotFound"),
        502: build_error_envelope_serializer("ListBranchesBadGateway"),
    },
)
class ListRepoBranchesView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = [BranchListSerializer]

    def get(self, request, repo):
        user = request.user
        repo_obj = GithubRepos.objects.filter(
            user_id=user, name__iexact=repo, is_deleted=False
        ).first()
        if not repo_obj:
            return error_response("Repository not found.", status_code=status.HTTP_404_NOT_FOUND)

        try:
            if user.is_github_installation_active and user.github_installation_id:
                owner = repo_obj.full_name.split("/", 1)[0]
                branches = service.list_repo_branches(owner, repo, user.github_installation_id)
            else:
                return error_response(
                    "No GitHub repository connection found.",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
        except RequestException:
            logger.exception("Failed to fetch branches for repo %s", repo)
            return error_response(
                "Unable to retrieve branches.",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

        return success_response(message="Branches listed successfully", data=branches)


@extend_schema(
    tags=["GitHub"],
    parameters=[
        OpenApiParameter(name="query", type=str, location=OpenApiParameter.QUERY, required=False, description="Search term for repo name (case-insensitive contains)"),
    ],
    responses={
        200: build_success_envelope_serializer("SearchReposResponse", _repo_item_serializer),
    },
)
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


@extend_schema(
    tags=["GitHub"],
    responses={
        200: build_success_envelope_serializer("DisconnectResponse"),
        400: build_error_envelope_serializer("DisconnectError"),
    },
)
class GitHubDisconnectView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = serializers.Serializer

    def post(self, request):
        user = request.user
        if not user.github_installation_id:
            return error_response(
                "GitHub repositories are not connected.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        GithubRepos.objects.filter(user_id=user).update(is_deleted=True, is_active=False)
        RepoBranch.objects.filter(repo__user_id=user).update(is_active=False)
        User.objects.filter(pk=user.pk).update(
            github_installation_access_token=None,
            github_installation_account_login=None,
            github_installation_id=None,
            github_installation_state=None,
            is_github_installation_active=False,
            github_username=user.github_oauth_username,
        )
        user.refresh_from_db()
        return success_response("GitHub repositories disconnected successfully.")


_scan_report_branch_serializer = inline_serializer(
    "ScanReportBranchData",
    fields={
        "branch": serializers.CharField(),
        "status": serializers.CharField(),
        "last_indexed_at": serializers.IntegerField(allow_null=True),
        "previous_scans": inline_serializer(
            "PreviousScanData",
            fields={
                "commit_url": serializers.URLField(),
                "commit_sha": serializers.CharField(),
                "indexed_at": serializers.IntegerField(),
            },
            many=True,
        ),
    },
)

@extend_schema(
    tags=["GitHub"],
    parameters=[
        OpenApiParameter(name="repo_id", type=int, location=OpenApiParameter.PATH, required=True, description="GitHub repository ID"),
    ],
    responses={
        200: build_success_envelope_serializer("ScanReportResponse", _scan_report_branch_serializer),
        404: build_error_envelope_serializer("ScanReportNotFound"),
    },
)
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
