from django.urls import path

from github.views import (
    GitHubCallbackView,
    GitHubInstallUrlView,
    GitHubRepositoriesView,
    GitHubRepositorySelectionView,
    GitHubWebhookView,
)

urlpatterns = [
    path("install-url/", GitHubInstallUrlView.as_view(), name="github-install-url"),
    path("callback/", GitHubCallbackView.as_view(), name="github-callback"),
    path("repositories/", GitHubRepositoriesView.as_view(), name="github-repositories"),
    path(
        "repositories/select/",
        GitHubRepositorySelectionView.as_view(),
        name="github-repository-selection",
    ),
    path("webhook/", GitHubWebhookView.as_view(), name="github-webhook"),
]