import logging
import secrets

from django.conf import settings
from django.shortcuts import redirect
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from requests.exceptions import RequestException

from auth.models import User
from common.responses import error_response, success_response
# from github.models import (
#     GitHubInstallation,
#     GitHubInstallationState,
# )
from github.services.github_app import GitHubAppService
from github.serializers import (
    GitHubCallbackQuerySerializer,
    DownloadRepoSerializer,
    BranchListSerializer
)

import re
logger = logging.getLogger(__name__)
service = GitHubAppService()


class GitHubInstallUrlView(APIView):
    """
    Generates the GitHub App installation URL for the authenticated user.
    This will give us permission to access the user's repositories based on the permissions granted during installation.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not settings.GITHUB_APP_SLUG:
            return error_response(
                "GitHub App slug is not configured.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        state = secrets.token_urlsafe(32)
        print("request.user.id:", request.user.id)

        User.objects.filter(id=request.user.id).update(github_installation_state=state)
        install_url = (
            f"https://github.com/apps/{settings.GITHUB_APP_SLUG}/installations/new?state={state}"
        )
        return success_response("GitHub installation URL generated.", data={"url": install_url})


class GitHubCallbackView(APIView):
    """
    Handles the callback from GitHub after the user installs the app.
    This will give access to the user's repositories based on the user permissions.
    Take installation_id and installation token from the response after successful installation
    and use the installation token for further API requests for user's repositories and other details.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        serializer = GitHubCallbackQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        state = serializer.validated_data["state"]
        installation_id = serializer.validated_data["installation_id"]

        # state_record = GitHubInstallationState.objects.filter(state=state, used=False).select_related("user").first()
        # if not state_record:
        #     return error_response(
        #         "Invalid or expired GitHub callback state.",
        #         status_code=status.HTTP_400_BAD_REQUEST,
        #     )

        # state_record.used = True
        # state_record.save(update_fields=["used"])

        try:
            installation_details = service.get_installation_details(installation_id)
        except RequestException:
            logger.exception("Failed to fetch GitHub installation details for %s", installation_id)
            return error_response(
                "Unable to fetch GitHub installation details.",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

        account = installation_details.get("account", {})
        print("account details", account)

        # account_login = account.get("login", "")
        # account_type = account.get("type", "")

        # GitHubInstallation.objects.update_or_create(
        #     user=state_record.user,
        #     defaults={
        #         "installation_id": installation_id,
        #         "account_login": account_login,
        #         "account_type": account_type,
        #     },
        # )
        github_username=account.get("login", "")
        print("installation_id: ", installation_id)

        User.objects.filter(github_installation_state=state).update(
            github_username=github_username,
            github_installation_id=installation_id,
        )

        # redirect_url = f"{settings.FRONTEND_URL.rstrip('/')}/dashboard"
        return success_response(message="installation successful")


class ListReposView(APIView):
    """
    Fetches the list of repositories accessible to the authenticated user based on their GitHub App installation.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_email=request.user
        user = User.objects.get(email=user_email)

        if not user:
            return error_response(
                "user not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        is_github_installation_active = user.is_github_installation_active
        installation_id = user.github_installation_id

        if not is_github_installation_active:
            return error_response(
                "Github installation is incomplete for this user.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        try:
            repositories = service.get_installation_repositories(installation_id)
        except RequestException:
            logger.exception(
                "Failed to fetch GitHub repositories for installation %s",
                installation_id,
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


# class GitHubRepositorySelectionView(APIView):
#     permission_classes = [IsAuthenticated]

#     def post(self, request):
#         serializer = GitHubRepositorySelectionSerializer(data=request.data)
#         serializer.is_valid(raise_exception=True)

#         installation = getattr(request.user, "github_installation", None)
#         if not installation:
#             return error_response(
#                 "No GitHub installation is associated with the current user.",
#                 status_code=status.HTTP_404_NOT_FOUND,
#             )

#         selections = serializer.validated_data["repositories"]
#         GitHubRepositorySelection.objects.filter(installation=installation).delete()

#         created_objects = [
#             GitHubRepositorySelection(
#                 installation=installation,
#                 repository_id=item["id"],
#                 name=item["name"],
#                 full_name=item["full_name"],
#                 private=item["private"],
#             )
#             for item in selections
#         ]
#         GitHubRepositorySelection.objects.bulk_create(created_objects)

#         return success_response(
#             "Repository selection saved successfully.",
#             data={"selected_count": len(created_objects)},
#         )


class GitHubWebhookView(APIView):
    """
    Handles incoming GitHub webhook events. Verifies the signature and processes events like installation, repository selection, and push events.
    """
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
        print("event:", event)

        payload = request.data
        print("payload: ", payload)

        logger.info(
            "GitHub webhook received event=%s installation_id=%s action=%s",
            event,
            payload.get("installation", {}).get("id"),
            payload.get("action"),
        )

        handler_name = f"handle_{event.replace('-', '_')}"
        handler = getattr(self, handler_name, self.handle_default)
        print("handler: ", handler)

        return handler(payload)

    def handle_installation(self, payload):
        installation = payload.get("installation", {})
        action = payload.get("action")
        installation_id = installation.get("id")
        print("installation_id:", installation_id)

        if action == "created":

            installation_token = service.get_installation_token(installation_id)
            # repos = service.get_installation_repositories(self, installation_id)

            User.objects.filter(github_installation_id=installation_id).update(
                github_installation_access_token=installation_token,
                is_github_installation_active=True
            )

        if action == "deleted" and installation_id:
            User.object.filter(github_installation_id=installation_id).update(
                github_installation_access_token=None,
                github_installation_state=None,
                is_github_installation_active=False
            )
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

class DownloadRepo(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DownloadRepoSerializer

    def post(self, request):
        user = User.objects.get(email=request.user)

        if not user:
            return error_response(
                "User not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        
        is_github_installation_active = user.is_github_installation_active
        installation_id = user.github_installation_id

        if not is_github_installation_active:
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

            # donwnload the repository using the installation token and repo_id
            service.download_repository(repo_full_name, installation_id, branch)

            # repositories = service.get_installation_repositories(installation.installation_id)
        except RequestException:
            logger.exception(
                "Failed to download repo for installation %s",
                installation_id,
            )
            return error_response(
                "Unable to download github repo.",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

        return success_response("GitHub repo downloaded successfully.")

class ListRepoBranchesView(APIView):
    permission_classes=[IsAuthenticated]
    serializer_class=[BranchListSerializer]

    def get(self, request, repo):
        user_email = request.user
        user = User.objects.get(email=user_email)
        owner = user.github_username
        installation_id = user.github_installation_id

        branches = service.list_repo_branches(owner, repo, installation_id)

        return success_response(message="branches listed successfully", data=branches)

class SearchReposView(APIView):
    permission_classes=[IsAuthenticated]
    
    def get(self, request):
        user_email=request.user
        user = User.objects.get(email=user_email)
        installation_id = user.github_installation_id
        query = request.query_params.get('query')

        repos = service.get_installation_repositories(installation_id)

        repos = [
            {
                "id": repo.get("id"),
                "name": repo.get("name"),
                "full_name": repo.get("full_name"),
                "private": repo.get("private", False),
            }
            for repo in repos
        ]

        filtered_repos = [
            repo
            for repo in repos
            if re.search(query, repo['name'], re.IGNORECASE)
        ]

        # formatted = [
        #     {
        #         "id": repo.get("id"),
        #         "name": repo.get("name"),
        #         "full_name": repo.get("full_name"),
        #         "private": repo.get("private", False),
        #     }
        #     for repo in filtered_repos
        # ]
        response_data = filtered_repos if len(filtered_repos) > 0 else repos

        return success_response(message="searched repos found", data=response_data)