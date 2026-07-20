from collections import defaultdict
from datetime import datetime, timedelta, timezone

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from admin_api.pagination import AdminPagination
from admin_api.permissions import IsAdminUser
from admin_api.serializers import (
    AdminErrorLogSerializer,
    AdminRepoSerializer,
    AdminScanJobSerializer,
    AdminStatsSerializer,
    AdminUserSerializer,
    AdminUserUpdateSerializer,
    ScanOverTimeSerializer,
)
from common.responses import error_response, success_response
from core.models import ChatSession
from github.models import BranchScan, BranchScanStatus, GithubRepos, RepoBranch, ScanError

User = get_user_model()

TODAY = "today"
ADMIN_DELETE = "admin_delete"


class _BaseAdminView:
    permission_classes = [IsAuthenticated, IsAdminUser]


class AdminStatsView(_BaseAdminView, APIView):
    def get(self, request):
        now = datetime.now(timezone.utc)
        thirty_days_ago = now - timedelta(days=30)

        start_of_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        today_ts = int(start_of_today.timestamp())
        thirty_days_ago_ts = int(thirty_days_ago.timestamp())

        total_users = User.objects.filter(is_deleted=False).count()

        active_users = User.objects.filter(
            is_deleted=False,
            last_login__gte=thirty_days_ago,
        ).count()

        total_repos = GithubRepos.objects.filter(is_deleted=False).count()

        scanned_repos = (
            BranchScan.objects.filter(status=BranchScanStatus.SCANNED)
            .values("repo_branch__repo")
            .distinct()
            .count()
        )

        total_chats = ChatSession.objects.filter(is_deleted=False).count()

        scans_today = BranchScan.objects.filter(started_at__gte=today_ts).count()

        failed_scans = BranchScan.objects.filter(status=BranchScanStatus.FAILED).count()

        completed_scans = BranchScan.objects.filter(
            status__in=[BranchScanStatus.SCANNED, BranchScanStatus.PARTIALLY_SCANNED],
            completed_at__isnull=False,
            started_at__isnull=False,
        )
        avg_duration = None
        durations = []
        for scan in completed_scans.iterator():
            durations.append(scan.completed_at - scan.started_at)
        if durations:
            avg_duration = int(sum(durations) / len(durations))

        data = AdminStatsSerializer(
            {
                "total_users": total_users,
                "active_users": active_users,
                "total_repos": total_repos,
                "scanned_repos": scanned_repos,
                "total_chats": total_chats,
                "scans_today": scans_today,
                "failed_scans": failed_scans,
                "avg_scan_duration_seconds": avg_duration,
            }
        ).data

        return success_response("Dashboard stats fetched.", data=data)


class ScansOverTimeView(_BaseAdminView, APIView):
    def get(self, request):
        now = datetime.now(timezone.utc)
        thirty_days_ago = now - timedelta(days=30)
        thirty_days_ago_ts = int(thirty_days_ago.timestamp())

        scans = BranchScan.objects.filter(started_at__gte=thirty_days_ago_ts).only(
            "started_at", "status"
        )

        daily = defaultdict(lambda: {"completed": 0, "failed": 0, "total": 0})
        for scan in scans:
            day = datetime.fromtimestamp(scan.started_at, tz=timezone.utc).date()
            daily[day]["total"] += 1
            if scan.status in (BranchScanStatus.SCANNED, BranchScanStatus.PARTIALLY_SCANNED):
                daily[day]["completed"] += 1
            elif scan.status == BranchScanStatus.FAILED:
                daily[day]["failed"] += 1

        results = []
        for i in range(30):
            day = (thirty_days_ago + timedelta(days=i)).date()
            entry = daily.get(day, {"completed": 0, "failed": 0, "total": 0})
            results.append({"date": day.isoformat(), **entry})

        return success_response("Scans over time fetched.", data=results)


class AdminUserListView(_BaseAdminView, generics.ListAPIView):
    queryset = User.objects.filter(is_deleted=False)
    serializer_class = AdminUserSerializer
    pagination_class = AdminPagination
    filter_backends = [SearchFilter]
    search_fields = ["email", "first_name", "last_name"]

    def get_queryset(self):
        qs = super().get_queryset().annotate(
            repo_count=Count("github_repos", filter=Q(github_repos__is_deleted=False)),
            chat_count=Count("chat_sessions", filter=Q(chat_sessions__is_deleted=False)),
        ).order_by("-created_at")

        role = self.request.query_params.get("role")
        if role in ("admin", "user"):
            qs = qs.filter(role=role)

        is_active = self.request.query_params.get("is_active")
        is_suspended = self.request.query_params.get("is_suspended")

        if is_suspended is not None:
            suspended = is_suspended.lower() in ("true", "1")
            qs = qs.filter(is_active=not suspended)
        elif is_active is not None:
            active = is_active.lower() in ("true", "1")
            qs = qs.filter(is_active=active)

        return qs

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return success_response(
                "Users fetched.",
                data=self.paginator.get_paginated_response(serializer.data).data,
            )
        serializer = self.get_serializer(queryset, many=True)
        return success_response("Users fetched.", data=serializer.data)


class AdminUserDetailView(_BaseAdminView, APIView):
    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk, is_deleted=False)
        user_with_counts = User.objects.filter(pk=user.pk).annotate(
            repo_count=Count("github_repos", filter=Q(github_repos__is_deleted=False)),
            chat_count=Count("chat_sessions", filter=Q(chat_sessions__is_deleted=False)),
        ).first()
        data = AdminUserSerializer(user_with_counts).data
        return success_response("User fetched.", data=data)

    def patch(self, request, pk):
        user = get_object_or_404(User, pk=pk, is_deleted=False)
        serializer = AdminUserUpdateSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        user_with_counts = User.objects.filter(pk=user.pk).annotate(
            repo_count=Count("github_repos", filter=Q(github_repos__is_deleted=False)),
            chat_count=Count("chat_sessions", filter=Q(chat_sessions__is_deleted=False)),
        ).first()
        data = AdminUserSerializer(user_with_counts).data
        return success_response("User updated.", data=data)

    def delete(self, request, pk):
        user = get_object_or_404(User, pk=pk, is_deleted=False)
        user.delete()
        return success_response("User deleted.", status_code=status.HTTP_204_NO_CONTENT)


class AdminUserSuspendView(_BaseAdminView, APIView):
    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk, is_deleted=False)
        user.is_active = False
        user.save(update_fields=["is_active", "updated_at"])
        return success_response("User suspended.", data={"detail": "User suspended"})


class AdminUserActivateView(_BaseAdminView, APIView):
    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk, is_deleted=False)
        user.is_active = True
        user.save(update_fields=["is_active", "updated_at"])
        return success_response("User activated.", data={"detail": "User activated"})


SCAN_STATUS_FILTER_MAP = {
    "pending": None,
    "running": ["scanning", "indexing"],
    "completed": ["scanned", "partially_scanned"],
    "failed": ["failed"],
}


class AdminScanListView(_BaseAdminView, generics.ListAPIView):
    queryset = BranchScan.objects.select_related(
        "repo_branch__repo__user_id"
    ).prefetch_related("errors").order_by("-started_at")
    serializer_class = AdminScanJobSerializer
    pagination_class = AdminPagination
    filter_backends = [SearchFilter]
    search_fields = [
        "repo_branch__repo__name",
        "repo_branch__repo__full_name",
        "repo_branch__repo__user_id__email",
    ]

    def get_queryset(self):
        qs = super().get_queryset()
        status_filter = self.request.query_params.get("status")
        if status_filter in SCAN_STATUS_FILTER_MAP:
            db_statuses = SCAN_STATUS_FILTER_MAP[status_filter]
            if db_statuses is not None:
                qs = qs.filter(status__in=db_statuses)
        return qs

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return success_response(
                "Scans fetched.",
                data=self.paginator.get_paginated_response(serializer.data).data,
            )
        serializer = self.get_serializer(queryset, many=True)
        return success_response("Scans fetched.", data=serializer.data)


class AdminScanDetailView(_BaseAdminView, APIView):
    def get(self, request, pk):
        scan = get_object_or_404(
            BranchScan.objects.select_related("repo_branch__repo__user_id").prefetch_related("errors"),
            pk=pk,
        )
        data = AdminScanJobSerializer(scan).data
        return success_response("Scan fetched.", data=data)


class AdminScanRetryView(_BaseAdminView, APIView):
    def post(self, request, pk):
        original = get_object_or_404(
            BranchScan.objects.select_related("repo_branch"), pk=pk
        )
        new_scan = BranchScan.objects.create(
            repo_branch=original.repo_branch,
            commit_sha=original.commit_sha,
            commit_url=original.commit_url,
            status=BranchScanStatus.SCANNING,
        )
        return success_response(
            "Scan retry triggered.",
            data={"detail": "Scan retry triggered"},
        )


class AdminRepoListView(_BaseAdminView, generics.ListAPIView):
    queryset = GithubRepos.objects.filter(is_deleted=False).select_related("user_id").order_by("-created_at")
    serializer_class = AdminRepoSerializer
    pagination_class = AdminPagination
    filter_backends = [SearchFilter]
    search_fields = ["name", "full_name", "user_id__email"]

    def get_queryset(self):
        qs = super().get_queryset().annotate(
            branch_count=Count("branches", filter=Q(branches__is_active=True)),
        )

        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        owner_id = self.request.query_params.get("owner_id")
        if owner_id:
            qs = qs.filter(user_id=owner_id)

        return qs

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return success_response(
                "Repos fetched.",
                data=self.paginator.get_paginated_response(serializer.data).data,
            )
        serializer = self.get_serializer(queryset, many=True)
        return success_response("Repos fetched.", data=serializer.data)


class AdminRepoDeleteView(_BaseAdminView, APIView):
    def delete(self, request, pk):
        repo = get_object_or_404(GithubRepos, pk=pk, is_deleted=False)
        repo.delete()
        return success_response("Repo deleted.", status_code=status.HTTP_204_NO_CONTENT)


class AdminRepoRescanView(_BaseAdminView, APIView):
    def post(self, request, pk):
        repo = get_object_or_404(GithubRepos, pk=pk, is_deleted=False)
        branch, _ = RepoBranch.objects.get_or_create(
            repo=repo,
            name=repo.default_branch,
            defaults={"is_active": True},
        )
        BranchScan.objects.create(
            repo_branch=branch,
            commit_sha=branch.commit_sha or "",
            commit_url=branch.commit_url or "",
            status=BranchScanStatus.SCANNING,
        )
        return success_response(
            "Re-scan triggered.",
            data={"detail": "Re-scan triggered"},
        )


class AdminLogListView(_BaseAdminView, generics.ListAPIView):
    queryset = ScanError.objects.select_related(
        "branch_scan__repo_branch__repo__user_id"
    ).order_by("-created_at")
    serializer_class = AdminErrorLogSerializer
    pagination_class = AdminPagination
    filter_backends = [SearchFilter]
    search_fields = [
        "error_message",
        "branch_scan__repo_branch__repo__full_name",
        "branch_scan__repo_branch__repo__user_id__email",
    ]

    def get_queryset(self):
        qs = super().get_queryset()

        level = self.request.query_params.get("level")
        if level:
            qs = qs.filter(error_type__icontains=level)

        source = self.request.query_params.get("source")
        if source:
            qs = qs.filter(error_type__icontains=source)

        return qs

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return success_response(
                "Logs fetched.",
                data=self.paginator.get_paginated_response(serializer.data).data,
            )
        serializer = self.get_serializer(queryset, many=True)
        return success_response("Logs fetched.", data=serializer.data)
