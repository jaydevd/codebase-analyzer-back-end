from django.contrib import admin

# from github.models import (
#     GitHubInstallation,
#     GitHubInstallationState,
#     GitHubRepositorySelection,
# )


# @admin.register(GitHubInstallation)
# class GitHubInstallationAdmin(admin.ModelAdmin):
#     list_display = ("user", "installation_id", "account_login", "account_type", "created_at")
#     search_fields = ("user__email", "account_login", "account_type")
#     readonly_fields = ("created_at", "updated_at")


# @admin.register(GitHubInstallationState)
# class GitHubInstallationStateAdmin(admin.ModelAdmin):
#     list_display = ("user", "state", "used", "created_at")
#     list_filter = ("used",)
#     readonly_fields = ("created_at",)


# @admin.register(GitHubRepositorySelection)
# class GitHubRepositorySelectionAdmin(admin.ModelAdmin):
#     list_display = ("installation", "repository_id", "full_name", "private", "created_at")
#     search_fields = ("full_name",)
#     readonly_fields = ("created_at", "updated_at")
