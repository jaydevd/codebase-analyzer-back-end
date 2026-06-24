from django.urls import path
from core.views import (
    QueryView,
    CreateChatSessionView,
    GetChatHistoryView,
    ChatSessionDetailView,
)

urlpatterns = [
    path("session/new", CreateChatSessionView.as_view(), name="new-chat-session"),
    path("session/<uuid:pk>/", ChatSessionDetailView.as_view(), name="session-detail"),
    path("query/", QueryView.as_view(), name="query"),
    path("history/", GetChatHistoryView.as_view(), name="chat-history"),
]
