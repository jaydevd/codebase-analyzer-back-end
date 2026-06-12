from django.shortcuts import render
from rest_framework.views import APIView
from embeddings.services.embed import EmbeddingService, index_branch_task
from common.responses import *
from github.services.github_app import GitHubAppService

service = EmbeddingService()
github_service = GitHubAppService()

class IndexRepoView(APIView):
    def post(self, request):

        owner      = request.data['owner']
        repo       = request.data['repo']
        branch     = request.data['branch']
        commit_sha = request.data['commit_sha']  # resolved in frontend/earlier step
        installation_id = request.data['installation_id']

        # fetch the tree (your existing code)
        # owner: str, repo: str, installation_id: int, branch:str = None
        tree_response = github_service.fetch_tree(owner, repo, installation_id, commit_sha)

        # run indexing in a background thread so the view returns immediately
        # in production, replace this with a Celery task
        index_branch_task.delay(owner, repo, branch, commit_sha, tree_response, installation_id)

        return success_response(
            message=f'Indexing {branch} in background. Poll /index-status/ to check progress.'
        )