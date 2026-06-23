from django.contrib import admin
from github.models import GithubRepos, RepoBranch


@admin.register(GithubRepos)
class GithubReposAdmin(admin.ModelAdmin):
    list_display = ("name", "full_name", "user_id", "status", "is_active", "is_deleted")
    list_filter = ("status", "is_active", "is_deleted")
    search_fields = ("name", "full_name", "user_id__email")


@admin.register(RepoBranch)
class RepoBranchAdmin(admin.ModelAdmin):
    list_display = ("repo", "name", "status", "commit_sha", "last_indexed_at")
    list_filter = ("status", "is_active")
    search_fields = ("name", "repo__full_name")
