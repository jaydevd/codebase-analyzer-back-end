from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from rest_framework import serializers

from github.models import BranchScan, GithubRepos, RepoBranch, ScanError
from core.models import ChatSession

User = get_user_model()


def _ts_to_datetime(ts):
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class AdminStatsSerializer(serializers.Serializer):
    total_users = serializers.IntegerField()
    active_users = serializers.IntegerField()
    total_repos = serializers.IntegerField()
    scanned_repos = serializers.IntegerField()
    total_chats = serializers.IntegerField()
    scans_today = serializers.IntegerField()
    failed_scans = serializers.IntegerField()
    avg_scan_duration_seconds = serializers.IntegerField(allow_null=True)


class ScanOverTimeSerializer(serializers.Serializer):
    date = serializers.DateField()
    completed = serializers.IntegerField()
    failed = serializers.IntegerField()
    total = serializers.IntegerField()


class AdminUserSerializer(serializers.ModelSerializer):
    github_username = serializers.SerializerMethodField()
    is_suspended = serializers.SerializerMethodField()
    repo_count = serializers.IntegerField(read_only=True, default=0)
    chat_count = serializers.IntegerField(read_only=True, default=0)
    last_login = serializers.DateTimeField(allow_null=True)
    created_at = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "github_username",
            "role",
            "is_active",
            "is_suspended",
            "is_github_installation_active",
            "repo_count",
            "chat_count",
            "last_login",
            "created_at",
        )

    def get_github_username(self, obj):
        return getattr(obj, "github_installation_account_login", None) or getattr(obj, "github_oauth_username", None) or getattr(obj, "github_username", None)

    def get_is_suspended(self, obj):
        return not obj.is_active

    def get_created_at(self, obj):
        return _ts_to_datetime(obj.created_at)


class AdminUserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "role")

    def validate_email(self, value):
        normalized = User.objects.normalize_email(value).lower()
        user = self.instance
        if User.objects.filter(email__iexact=normalized).exclude(pk=user.pk).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return normalized


SCAN_STATUS_MAP = {
    "scanning": "running",
    "indexing": "running",
    "scanned": "completed",
    "partially_scanned": "completed",
    "failed": "failed",
}


class AdminScanJobSerializer(serializers.ModelSerializer):
    repository_id = serializers.UUIDField(source="repo_branch.repo.id")
    repository_name = serializers.CharField(source="repo_branch.repo.name")
    repository_full_name = serializers.CharField(source="repo_branch.repo.full_name")
    user_id = serializers.UUIDField(source="repo_branch.repo.user_id.id")
    user_email = serializers.EmailField(source="repo_branch.repo.user_id.email")
    branch = serializers.CharField(source="repo_branch.name")
    status = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()
    error_message = serializers.SerializerMethodField()
    error_log = serializers.SerializerMethodField()
    started_at = serializers.SerializerMethodField()
    completed_at = serializers.SerializerMethodField()
    duration_seconds = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()

    class Meta:
        model = BranchScan
        fields = (
            "id",
            "repository_id",
            "repository_name",
            "repository_full_name",
            "user_id",
            "user_email",
            "branch",
            "commit_sha",
            "status",
            "progress",
            "error_message",
            "error_log",
            "started_at",
            "completed_at",
            "duration_seconds",
            "created_at",
        )

    def get_status(self, obj):
        return SCAN_STATUS_MAP.get(obj.status, "pending")

    def get_progress(self, obj):
        if obj.status in ("scanned", "partially_scanned"):
            return 100
        if obj.status == "failed":
            try:
                return min(int(obj.repo_branch.repo.branches.filter(scans=obj).first().last_error_message or "0"), 100)
            except (ValueError, AttributeError):
                return 0
        return 0

    def get_error_message(self, obj):
        first_error = obj.errors.first()
        if first_error:
            return first_error.error_message
        return obj.repo_branch.last_error_message

    def get_error_log(self, obj):
        first_error = obj.errors.first()
        if first_error:
            return first_error.stack_trace
        return None

    def get_started_at(self, obj):
        return _ts_to_datetime(obj.started_at)

    def get_completed_at(self, obj):
        return _ts_to_datetime(obj.completed_at)

    def get_duration_seconds(self, obj):
        if obj.started_at and obj.completed_at:
            return obj.completed_at - obj.started_at
        return None

    def get_created_at(self, obj):
        return _ts_to_datetime(obj.created_at)


class AdminRepoSerializer(serializers.ModelSerializer):
    owner_id = serializers.UUIDField(source="user_id.id")
    owner_email = serializers.EmailField(source="user_id.email")
    branch_count = serializers.IntegerField(read_only=True, default=0)
    language = serializers.SerializerMethodField()
    file_count = serializers.SerializerMethodField()
    chunk_count = serializers.SerializerMethodField()
    last_scanned = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()

    class Meta:
        model = GithubRepos
        fields = (
            "id",
            "name",
            "full_name",
            "owner_id",
            "owner_email",
            "private",
            "language",
            "status",
            "branch_count",
            "file_count",
            "chunk_count",
            "last_scanned",
            "created_at",
        )

    def get_language(self, obj):
        return None

    def get_file_count(self, obj):
        return None

    def get_chunk_count(self, obj):
        return None

    def get_last_scanned(self, obj):
        latest = obj.branches.exclude(last_indexed_at=None).order_by("-last_indexed_at").first()
        if latest and latest.last_indexed_at:
            return _ts_to_datetime(latest.last_indexed_at)
        return None

    def get_created_at(self, obj):
        return _ts_to_datetime(obj.created_at)


class AdminErrorLogSerializer(serializers.ModelSerializer):
    level = serializers.SerializerMethodField()
    source = serializers.SerializerMethodField()
    message = serializers.CharField(source="error_message")
    repository_name = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()

    class Meta:
        model = ScanError
        fields = (
            "id",
            "level",
            "source",
            "message",
            "repository_name",
            "user_email",
            "stack_trace",
            "created_at",
        )

    def get_level(self, obj):
        return "error"

    def get_source(self, obj):
        return "codebase-analyzer.worker"

    def get_repository_name(self, obj):
        if obj.branch_scan and obj.branch_scan.repo_branch and obj.branch_scan.repo_branch.repo:
            return obj.branch_scan.repo_branch.repo.full_name
        return None

    def get_user_email(self, obj):
        if obj.branch_scan and obj.branch_scan.repo_branch and obj.branch_scan.repo_branch.repo and obj.branch_scan.repo_branch.repo.user_id:
            return obj.branch_scan.repo_branch.repo.user_id.email
        return None

    def get_created_at(self, obj):
        return _ts_to_datetime(obj.created_at)
