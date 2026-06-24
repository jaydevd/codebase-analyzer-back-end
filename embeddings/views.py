from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from embeddings.services.embed import index_branch_task
from common.models import get_unix_timestamp
from common.responses import error_response, success_response
from github.models import GithubRepos, RepoBranch, RepoIndexStatus, BranchScan
from github.services.github_app import github_service
from auth.models import User

class IndexRepoView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        repo_id = request.data.get("repo_id")
        branch = request.data.get("branch")
        commit_sha = request.data.get("commit_sha")

        if not all([repo_id, branch, commit_sha]):
            return error_response("Missing required fields.", status_code=400)

        user = User.objects.get(email=request.user)
        installation_id = user.github_installation_id
        owner = user.github_username

        github_repo = GithubRepos.objects.filter(
            repo_id=repo_id,
            user_id=request.user,
            is_deleted=False,
        ).first()
        if not github_repo:
            return error_response("Repository not found.", status_code=404)

        repo = github_repo.name
        commit_url = f"https://github.com/{github_repo.full_name}/commit/{commit_sha}"

        github_repo.status = RepoIndexStatus.SCANNING
        github_repo.save(update_fields=["status"])

        repo_branch, _ = RepoBranch.objects.update_or_create(
            repo=github_repo,
            name=branch,
            defaults={
                "commit_sha": commit_sha,
                "commit_url": commit_url,
                "status": RepoIndexStatus.SCANNING,
                "is_active": True,
            },
        )

        scan = BranchScan.objects.create(
            repo_branch=repo_branch,
            commit_sha=commit_sha,
            commit_url=commit_url,
            status=RepoIndexStatus.SCANNING,
            started_at=get_unix_timestamp(),
        )

        tree_response = github_service.fetch_tree(owner, repo, installation_id, commit_sha)

        index_branch_task.delay(
            owner, repo, branch, commit_sha, tree_response, installation_id, repo_id, str(scan.id)
        )

        return success_response(
            message=f"Indexing {branch} in background."
        )
