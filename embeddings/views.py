from django.shortcuts import render
from rest_framework.views import APIView
from embeddings.services.embed import EmbeddingService
from common.responses import *
from github.services.github_app import GitHubAppService
import threading

service = EmbeddingService()
github_service = GitHubAppService()

class IndexRepoView(APIView):
    def post(self, request):
        owner      = request.POST.get('owner')
        repo       = request.POST.get('repo')
        branch     = request.POST.get('branch', 'main')
        commit_sha = request.POST.get('commit_sha')  # resolved in frontend/earlier step
        installation_id = request.POST.get('installation_id')

        # fetch the tree (your existing code)
        # owner: str, repo: str, installation_id: int, branch:str = None
        tree_response = github_service.fetch_tree(owner, repo, installation_id, commit_sha)

        # run indexing in a background thread so the view returns immediately
        # in production, replace this with a Celery task
        service.index_branch.delay(owner, repo, branch, commit_sha, tree_response, installation_id)

        return success_response(
            status='indexing_started',
            message=f'Indexing {branch} in background. Poll /index-status/ to check progress.'
        )