from django.urls import path

from github.views import (
    GitHubCallbackView,
    GitHubInstallUrlView,
    ListReposView,
    # GitHubRepositorySelectionView,
    GitHubWebhookView,
    DownloadRepo
)

urlpatterns = [
    path("install-url/", GitHubInstallUrlView.as_view(), name="github-install-url"),
    path("callback/", GitHubCallbackView.as_view(), name="github-callback"),
    path("repos/", ListReposView.as_view(), name="github-repos"),
    path(
        "repos/download/",
        DownloadRepo.as_view(),
        name="github-repo-download",
    ),
    path("webhook/", GitHubWebhookView.as_view(), name="github-webhook"),
]