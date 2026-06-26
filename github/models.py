import uuid

from django.conf import settings
from django.db import models
from common.models import get_unix_timestamp


class RepoIndexStatus(models.TextChoices):
    NOT_SCANNED = "not_scanned", "Not Scanned"
    SCANNING = "scanning", "Scanning"
    SCANNED = "scanned", "Scanned"
    PARTIALLY_SCANNED = "partially_scanned", "Partially Scanned"
    FAILED = "failed", "Failed"


class GithubRepos(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo_id = models.BigIntegerField(unique=True)
    name = models.CharField(max_length=512)
    full_name = models.CharField(max_length=512)
    private = models.BooleanField(default=False)
    default_branch = models.CharField(max_length=256, default="main")
    user_id = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="github_repos",
    )
    is_deleted = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    status = models.CharField(
        max_length=20,
        choices=RepoIndexStatus.choices,
        default=RepoIndexStatus.NOT_SCANNED,
    )
    created_at = models.BigIntegerField(default=get_unix_timestamp, editable=False)
    updated_at = models.BigIntegerField(default=get_unix_timestamp)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.full_name


class RepoBranch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo = models.ForeignKey(
        GithubRepos,
        on_delete=models.CASCADE,
        related_name="branches",
    )
    name = models.CharField(max_length=256)
    commit_sha = models.CharField(max_length=64, null=True, blank=True)
    commit_url = models.CharField(max_length=512, null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=RepoIndexStatus.choices,
        default=RepoIndexStatus.NOT_SCANNED,
    )
    last_indexed_at = models.BigIntegerField(null=True, blank=True)
    last_error_message = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.BigIntegerField(default=get_unix_timestamp, editable=False)
    updated_at = models.BigIntegerField(default=get_unix_timestamp)

    class Meta:
        unique_together = ("repo", "name")
        ordering = ("name",)

    def __str__(self):
        return f"{self.repo.full_name}/{self.name}"


class BranchScanStatus(models.TextChoices):
    SCANNING = "scanning", "Scanning"
    SCANNED = "scanned", "Scanned"
    PARTIALLY_SCANNED = "partially_scanned", "Partially Scanned"
    FAILED = "failed", "Failed"


class BranchScan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo_branch = models.ForeignKey(
        RepoBranch,
        on_delete=models.CASCADE,
        related_name="scans",
    )
    commit_sha = models.CharField(max_length=64)
    commit_url = models.CharField(max_length=512)
    status = models.CharField(
        max_length=20,
        choices=BranchScanStatus.choices,
        default=BranchScanStatus.SCANNING,
    )
    started_at = models.BigIntegerField(default=get_unix_timestamp)
    completed_at = models.BigIntegerField(null=True, blank=True)
    created_at = models.BigIntegerField(default=get_unix_timestamp, editable=False)

    class Meta:
        ordering = ("-started_at",)

    def __str__(self):
        return f"{self.repo_branch}@{self.commit_sha[:8]}"


class ScanError(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch_scan = models.ForeignKey(
        BranchScan,
        on_delete=models.SET_NULL,
        null=True,
        related_name="errors",
    )
    error_message = models.TextField()
    error_type = models.CharField(max_length=100)
    stack_trace = models.TextField(null=True, blank=True)
    created_at = models.BigIntegerField(default=get_unix_timestamp, editable=False)
    is_resolved = models.BooleanField(default=False)
    resolved_at = models.BigIntegerField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    resolution_notes = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"[{self.error_type}] {self.error_message[:100]}"
