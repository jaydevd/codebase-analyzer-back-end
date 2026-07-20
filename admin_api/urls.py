from django.urls import path

from admin_api.views import (
    AdminLogListView,
    AdminRepoDeleteView,
    AdminRepoListView,
    AdminRepoRescanView,
    AdminScanDetailView,
    AdminScanListView,
    AdminScanRetryView,
    AdminStatsView,
    AdminUserActivateView,
    AdminUserDetailView,
    AdminUserListView,
    AdminUserSuspendView,
    ScansOverTimeView,
)

urlpatterns = [
    # Dashboard
    path("stats/", AdminStatsView.as_view(), name="admin-stats"),
    path("stats/scans-over-time/", ScansOverTimeView.as_view(), name="admin-scans-over-time"),
    # Users
    path("users/", AdminUserListView.as_view(), name="admin-user-list"),
    path("users/<uuid:pk>/", AdminUserDetailView.as_view(), name="admin-user-detail"),
    path("users/<uuid:pk>/suspend/", AdminUserSuspendView.as_view(), name="admin-user-suspend"),
    path("users/<uuid:pk>/activate/", AdminUserActivateView.as_view(), name="admin-user-activate"),
    # Scans
    path("scans/", AdminScanListView.as_view(), name="admin-scan-list"),
    path("scans/<uuid:pk>/", AdminScanDetailView.as_view(), name="admin-scan-detail"),
    path("scans/<uuid:pk>/retry/", AdminScanRetryView.as_view(), name="admin-scan-retry"),
    # Repos
    path("repos/", AdminRepoListView.as_view(), name="admin-repo-list"),
    path("repos/<uuid:pk>/", AdminRepoDeleteView.as_view(), name="admin-repo-delete"),
    path("repos/<uuid:pk>/rescan/", AdminRepoRescanView.as_view(), name="admin-repo-rescan"),
    # Logs
    path("logs/", AdminLogListView.as_view(), name="admin-log-list"),
]
