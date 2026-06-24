from django.urls import path

from github.views import (
    GitHubCallbackView,
    GitHubInstallUrlView,
    ListReposView,
    GitHubWebhookView,
    DownloadRepo,
    ListRepoBranchesView,
    SearchReposView,
    RepoScanReportView,
)

urlpatterns = [
    path("install-url/", GitHubInstallUrlView.as_view(), name="github-install-url"),
    path("callback/", GitHubCallbackView.as_view(), name="github-callback"),
    path("repos/", ListReposView.as_view(), name="github-repos"),
    path("repos/search/", SearchReposView.as_view(), name="github-repos-search"),
    path("repos/<str:repo>/branches/", ListRepoBranchesView.as_view(), name="github-repo-branches"),
    path("repos/<int:repo_id>/scan-report/", RepoScanReportView.as_view(), name="github-repo-scan-report"),
    path(
        "repo/download/",
        DownloadRepo.as_view(),
        name="github-repo-download",
    ),
    path("webhook/", GitHubWebhookView.as_view(), name="github-webhook"),
]
