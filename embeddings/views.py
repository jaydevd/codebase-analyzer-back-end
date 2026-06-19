from rest_framework.views import APIView
from embeddings.services.embed import index_branch_task
from common.responses import *
from github.services.github_app import github_service

class IndexRepoView(APIView):
    def post(self, request):

        owner      = request.data['owner']
        repo       = request.data['repo']
        branch     = request.data['branch']
        commit_sha = request.data['commit_sha']  # resolved in frontend/earlier step
        installation_id = request.data['installation_id']

        # fetch the tree (your existing code)
        # owner: str, repo: str, installation_id: int, branch:str = None
        print("index_repo_view: getting tree for the repo")
        tree_response = github_service.fetch_tree(owner, repo, installation_id, commit_sha)
        print("index_repo_view: tree response received.")
        # run indexing in a background thread so the view returns immediately
        # in production, replace this with a Celery task
        print("index_repo_view: starting inexing repo")
        index_branch_task.delay(owner, repo, branch, commit_sha, tree_response, installation_id)
        print("index_repo_view: index created")

        return success_response(
            message=f'Indexing {branch} in background. Poll /index-status/ to check progress.'
        )