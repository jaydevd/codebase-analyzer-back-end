import logging
import secrets

from django.conf import settings
from django.shortcuts import redirect
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from requests.exceptions import RequestException

from common.responses import error_response, success_response
from github.models import (
    GitHubInstallation,
    GitHubInstallationState,
    GitHubRepositorySelection,
)
from github.services.github_app import GitHubAppService
from github.serializers import (
    GitHubCallbackQuerySerializer,
    GitHubRepositorySelectionSerializer,
)

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
        GitHubInstallationState.objects.create(user=request.user, state=state)
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
        GitHubInstallationState.objects.filter(state=state, used=True).delete()

        state_record = GitHubInstallationState.objects.filter(state=state, used=False).select_related("user").first()
        if not state_record:
            return error_response(
                "Invalid or expired GitHub callback state.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        state_record.used = True
        state_record.save(update_fields=["used"])

        try:
            installation_details = service.get_installation_details(installation_id)
        except RequestException:
            logger.exception("Failed to fetch GitHub installation details for %s", installation_id)
            return error_response(
                "Unable to fetch GitHub installation details.",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

        account = installation_details.get("account", {})
        account_login = account.get("login", "")
        account_type = account.get("type", "")

        GitHubInstallation.objects.update_or_create(
            user=state_record.user,
            defaults={
                "installation_id": installation_id,
                "account_login": account_login,
                "account_type": account_type,
            },
        )

        redirect_url = f"{settings.FRONTEND_URL.rstrip('/')}/github/success"
        return redirect(redirect_url)


class GitHubRepositoriesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        installation = getattr(request.user, "github_installation", None)
        if not installation:
            return error_response(
                "GitHub installation has not been completed for the current user.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        try:
            repositories = service.get_installation_repositories(installation.installation_id)
        except RequestException:
            logger.exception(
                "Failed to fetch GitHub repositories for installation %s",
                installation.installation_id,
            )
            return error_response(
                "Unable to retrieve GitHub repositories.",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

        formatted = [
            {
                "id": repo.get("id"),
                "name": repo.get("name"),
                "full_name": repo.get("full_name"),
                "private": repo.get("private", False),
            }
            for repo in repositories
        ]
        return success_response("GitHub repositories fetched successfully.", data=formatted)


class GitHubRepositorySelectionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = GitHubRepositorySelectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        installation = getattr(request.user, "github_installation", None)
        if not installation:
            return error_response(
                "No GitHub installation is associated with the current user.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        selections = serializer.validated_data["repositories"]
        GitHubRepositorySelection.objects.filter(installation=installation).delete()

        created_objects = [
            GitHubRepositorySelection(
                installation=installation,
                repository_id=item["id"],
                name=item["name"],
                full_name=item["full_name"],
                private=item["private"],
            )
            for item in selections
        ]
        GitHubRepositorySelection.objects.bulk_create(created_objects)

        return success_response(
            "Repository selection saved successfully.",
            data={"selected_count": len(created_objects)},
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

    def handle_installation(self, payload):
        installation = payload.get("installation", {})
        action = payload.get("action")
        installation_id = installation.get("id")

        if action == "deleted" and installation_id:
            GitHubInstallation.objects.filter(installation_id=installation_id).delete()
            logger.info("Deleted GitHub installation %s after webhook installation.deleted", installation_id)

        return success_response("GitHub installation event processed.")

    def handle_installation_repositories(self, payload):
        return success_response("GitHub installation_repositories event processed.")

    def handle_push(self, payload):
        repository = payload.get("repository", {}).get("full_name")
        ref = payload.get("ref")
        logger.info("Received push event for %s on ref %s", repository, ref)
        return success_response("GitHub push event processed.")

    def handle_default(self, payload):
        return success_response("GitHub webhook received.")
