import uuid

from django.conf import settings
from django.db import models
from auth.models import User

# class GitHubInstallationState(models.Model):
#     user = models.ForeignKey(
#         settings.AUTH_USER_MODEL,
#         on_delete=models.CASCADE,
#         related_name="github_install_states",
#     )
#     state = models.CharField(max_length=64, unique=True)
#     created_at = models.DateTimeField(auto_now_add=True)
#     used = models.BooleanField(default=False)

#     def __str__(self) -> str:
#         return f"GitHubInstallationState(user={self.user_id}, state={self.state}, used={self.used})"


# class GitHubInstallation(models.Model):
#     user = models.OneToOneField(
#         settings.AUTH_USER_MODEL,
#         on_delete=models.CASCADE,
#         related_name="github_installation",
#     )
#     installation_id = models.BigIntegerField(unique=True)
#     account_login = models.CharField(max_length=255)
#     account_type = models.CharField(max_length=64)
#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)

#     def __str__(self) -> str:
#         return f"{self.account_login} ({self.account_type})"


# class GitHubRepositorySelection(models.Model):
#     installation = models.ForeignKey(
#         "GitHubInstallation",
#         on_delete=models.CASCADE,
#         related_name="selected_repositories",
#     )
#     repository_id = models.BigIntegerField()
#     full_name = models.CharField(max_length=512)
#     name = models.CharField(max_length=255)
#     private = models.BooleanField(default=False)
#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)

#     class Meta:
#         unique_together = ("installation", "repository_id")

#     def __str__(self) -> str:
#         return self.full_name

class GithubRepos(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo_id = models.BigIntegerField(unique=True)
    repo_name = models.CharField(max_length=512)
    user_id = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="github_repos",
    )