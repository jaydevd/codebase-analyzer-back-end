from django.urls import path
from embeddings.views import IndexRepoView

urlpatterns = [
    path("repos/index/", IndexRepoView.as_view(), name="index-repo")
]